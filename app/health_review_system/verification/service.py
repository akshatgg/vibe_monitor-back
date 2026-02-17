"""
Verification service for health review findings.

Two-phase approach:
  Phase B — discover_infrastructure(): ReAct agent explores the repo tree to find
            global middleware, instrumentation, tracing, error handling. Runs ONCE.
  Phase C — verify_gaps(): For each rule group, an agent backtracks 20 sample gaps
            through the codebase to check if infrastructure covers them.
            Confidence threshold decides if the group is false_alarm or genuine.

No hardcoded file paths or framework assumptions anywhere.
"""

import asyncio
import hashlib
import json
import logging
from collections import defaultdict
from typing import Dict, List

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import StructuredTool
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.health_review_system.rule_engine.schemas import DetectedProblem
from app.health_review_system.tools import list_files, read_file, search_files

from .prompts import (
    DISCOVERY_SYSTEM_PROMPT,
    DISCOVERY_USER_PROMPT,
    IDENTIFY_CONFIG_FILES_SYSTEM_PROMPT,
    IDENTIFY_CONFIG_FILES_USER_PROMPT,
    VERIFICATION_SYSTEM_PROMPT,
    VERIFICATION_USER_PROMPT,
)
from .schemas import (
    CodebaseContext,
    GapVerdict,
    GapVerdictResult,
    VerificationResult,
)

logger = logging.getLogger(__name__)


def compute_gap_fingerprint(problem: DetectedProblem) -> str:
    """Compute a stable fingerprint for cross-review gap tracking."""
    key_parts = [
        problem.rule_id,
        "|".join(sorted(problem.affected_files)),
        "|".join(sorted(problem.affected_functions)),
    ]
    key = "::".join(key_parts)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _build_tools(
    repository_id: str, db: AsyncSession
) -> List[StructuredTool]:
    """Build verification tools with repository_id and db pre-bound."""

    async def _read_file(file_path: str) -> str:
        return await read_file.coroutine(
            file_path=file_path, repository_id=repository_id, db=db
        )

    async def _search_files(query: str) -> str:
        return await search_files.coroutine(
            query=query, repository_id=repository_id, db=db
        )

    async def _list_files(pattern: str) -> str:
        return await list_files.coroutine(
            pattern=pattern, repository_id=repository_id, db=db
        )

    bound_read = StructuredTool.from_function(
        coroutine=_read_file,
        name="read_file",
        description=read_file.description,
    )
    bound_search = StructuredTool.from_function(
        coroutine=_search_files,
        name="search_files",
        description=search_files.description,
    )
    bound_list = StructuredTool.from_function(
        coroutine=_list_files,
        name="list_files",
        description=list_files.description,
    )
    return [bound_read, bound_search, bound_list]


def format_repo_tree(repo_tree: List[dict]) -> str:
    """Format repo tree as compact text for the LLM prompt.

    For large repos (500+ files), groups by directory to stay within token limits.
    """
    if len(repo_tree) <= 500:
        lines = []
        for entry in repo_tree:
            lines.append(
                f"  {entry['file_path']}  ({entry['language']}, {entry['line_count']} lines)"
            )
        return "\n".join(lines)

    # Compact mode: group by directory
    return _compact_repo_tree(repo_tree)


def _compact_repo_tree(repo_tree: List[dict]) -> str:
    """Group files by directory for large repos."""
    dirs: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    dir_file_count: Dict[str, int] = defaultdict(int)

    for entry in repo_tree:
        path = entry["file_path"]
        parts = path.rsplit("/", 1)
        directory = parts[0] + "/" if len(parts) > 1 else "./"
        lang = entry["language"] or "unknown"
        dirs[directory][lang] += 1
        dir_file_count[directory] += 1

    lines = []
    for directory in sorted(dirs.keys()):
        lang_parts = ", ".join(
            f"{count} {lang}" for lang, count in sorted(dirs[directory].items())
        )
        total = dir_file_count[directory]
        lines.append(f"  {directory} ({total} files: {lang_parts})")

    return "\n".join(lines)


class VerificationService:
    """
    Verifies rule engine findings using a two-phase LLM approach.

    Phase B: discover_infrastructure() — one ReAct agent discovers the codebase
    Phase C: verify_gaps() — per-group agent backtracks gaps through the codebase
    """

    def __init__(self, llm: BaseChatModel, db: AsyncSession, repository_id: str):
        self.llm = llm
        self.db = db
        self.repository_id = repository_id
        self.tools = _build_tools(repository_id, db)

    # ------------------------------------------------------------------
    # Phase B: Infrastructure Discovery
    # ------------------------------------------------------------------

    async def discover_infrastructure(
        self,
        repo_tree: List[dict],
        gap_rule_ids: List[str],
        callbacks: list = None,
    ) -> CodebaseContext:
        """Discover global infrastructure using a ReAct agent.

        The agent receives the repo tree and explores the codebase to build
        a CodebaseContext. Runs ONCE, not per rule type.
        """
        tree_text = format_repo_tree(repo_tree)
        rule_ids_text = ", ".join(sorted(set(gap_rule_ids)))

        # Inject the CodebaseContext JSON schema into the system prompt
        schema_json = json.dumps(CodebaseContext.model_json_schema(), indent=2)
        system_prompt = DISCOVERY_SYSTEM_PROMPT.format(
            codebase_context_schema=schema_json
        )
        # Escape curly braces for LangChain template (the JSON schema contains
        # literal { and } which ChatPromptTemplate would interpret as variables)
        system_prompt_escaped = system_prompt.replace("{", "{{").replace("}", "}}")

        user_prompt = DISCOVERY_USER_PROMPT.format(
            repo_tree=tree_text,
            gap_rule_ids=rule_ids_text,
        )

        logger.info(
            f"[LLM][discovery] Starting infrastructure discovery "
            f"({len(repo_tree)} files, rule_ids={rule_ids_text})"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt_escaped),
            ("human", "{user_input}"),
            ("placeholder", "{agent_scratchpad}"),
        ])

        agent = create_tool_calling_agent(self.llm, self.tools, prompt)
        executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            max_iterations=200,  # High safety cap; real limit enforced by LLMBudgetCallback
            return_intermediate_steps=True,
            handle_parsing_errors="Output valid JSON matching the CodebaseContext schema.",
            verbose=False,
        )

        invoke_config = {"callbacks": callbacks} if callbacks else {}

        try:
            result = await executor.ainvoke(
                {"user_input": user_prompt}, config=invoke_config
            )
            output_text = result.get("output", "{}")

            # Log tool calls
            intermediate_steps = result.get("intermediate_steps", [])
            files_read = []
            for i, step in enumerate(intermediate_steps):
                action = step[0]
                tool_output = step[1] if len(step) > 1 else ""
                tool_name = getattr(action, "tool", "unknown")
                tool_input = getattr(action, "tool_input", "")
                logger.info(
                    f"[LLM][discovery] {tool_name}({tool_input}) → {str(tool_output)[:200]}"
                )
                if tool_name == "read_file":
                    fp = tool_input.get("file_path", "") if isinstance(tool_input, dict) else str(tool_input)
                    files_read.append(fp)

            logger.info(
                f"[LLM][discovery] Agent done: {len(intermediate_steps)} tool calls, "
                f"{len(files_read)} files read: {files_read}"
            )

            context = self._parse_codebase_context(output_text)
            logger.info(
                f"[LLM][discovery] Result: "
                f"{len(context.global_http_metrics)} HTTP, "
                f"{len(context.global_db_instrumentation)} DB, "
                f"{len(context.global_tracing)} tracing, "
                f"{len(context.global_error_handling)} error handling, "
                f"infra_files={context.infrastructure_files}"
            )
            return context

        except Exception as e:
            logger.error(f"Infrastructure discovery failed: {e}", exc_info=True)
            return CodebaseContext(
                summary=f"Discovery failed: {str(e)[:200]}",
            )

    # ------------------------------------------------------------------
    # Node 1: Identify Config/Middleware Files (single LLM call)
    # ------------------------------------------------------------------

    async def identify_config_files(
        self,
        repo_tree: List[dict],
        gap_rule_ids: List[str],
        callbacks: list = None,
    ) -> List[str]:
        """Identify candidate config/middleware files from file names only.

        Single LLM call — no tools needed. The LLM sees only file paths
        and returns a list of files likely to contain middleware/config.
        """
        tree_text = format_repo_tree(repo_tree)
        rule_ids_text = ", ".join(sorted(set(gap_rule_ids)))

        logger.info(
            f"[LLM][identify_config] Starting config file identification "
            f"({len(repo_tree)} files, rule_ids={rule_ids_text})"
        )

        messages = [
            ("system", IDENTIFY_CONFIG_FILES_SYSTEM_PROMPT),
            ("human", IDENTIFY_CONFIG_FILES_USER_PROMPT.format(
                repo_tree=tree_text,
                gap_rule_ids=rule_ids_text,
            )),
        ]

        invoke_config = {"callbacks": callbacks} if callbacks else {}

        try:
            response = await self.llm.ainvoke(messages, config=invoke_config)
            output_text = response.content if hasattr(response, "content") else str(response)

            # Parse JSON array of file paths
            json_str = output_text.strip()
            if json_str.startswith("```"):
                lines = json_str.split("\n")
                json_str = "\n".join(
                    line for line in lines if not line.strip().startswith("```")
                )

            candidate_files = json.loads(json_str)
            if not isinstance(candidate_files, list):
                candidate_files = []

            # Filter to only files that exist in the repo tree
            tree_paths = {entry["file_path"] for entry in repo_tree}
            candidate_files = [f for f in candidate_files if f in tree_paths]

            logger.info(
                f"[LLM][identify_config] Identified {len(candidate_files)} candidate files"
            )
            return candidate_files

        except Exception as e:
            logger.error(f"Config file identification failed: {e}", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Node 2: Extract From Single File (called once per file in graph loop)
    # ------------------------------------------------------------------

    MAX_LINES_PER_FILE = 300

    async def extract_from_single_file(
        self,
        file_path: str,
        gap_rule_ids: List[str],
        callbacks: list = None,
    ) -> List[dict]:
        """Extract instrumentation patterns from a single file.

        One LLM call per file. Returns a list of extracted instrumentation
        dicts (may be empty if the file has nothing relevant).
        """
        from app.code_parser.repository import ParsedFileRepository
        from .prompts import EXTRACT_SINGLE_FILE_SYSTEM_PROMPT, EXTRACT_SINGLE_FILE_USER_PROMPT

        file_crud = ParsedFileRepository(self.db)
        content = await file_crud.get_content(self.repository_id, file_path)

        if not content:
            logger.warning(f"[LLM][extract] Could not read {file_path}")
            return []

        # Truncate large files
        lines = content.split("\n")
        if len(lines) > self.MAX_LINES_PER_FILE:
            content = "\n".join(lines[:self.MAX_LINES_PER_FILE])
            content += f"\n\n... truncated ({len(lines)} lines total, showing first {self.MAX_LINES_PER_FILE})"

        rule_ids_text = ", ".join(sorted(set(gap_rule_ids)))

        logger.info(f"[LLM][extract] Processing {file_path} ({len(lines)} lines)")

        messages = [
            ("system", EXTRACT_SINGLE_FILE_SYSTEM_PROMPT),
            ("human", EXTRACT_SINGLE_FILE_USER_PROMPT.format(
                file_path=file_path,
                file_content=content,
                gap_rule_ids=rule_ids_text,
            )),
        ]

        invoke_config = {"callbacks": callbacks} if callbacks else {}

        try:
            response = await self.llm.ainvoke(messages, config=invoke_config)
            output_text = response.content if hasattr(response, "content") else str(response)

            # Parse JSON array
            json_str = output_text.strip()
            if json_str.startswith("```"):
                json_lines = json_str.split("\n")
                json_str = "\n".join(
                    line for line in json_lines if not line.strip().startswith("```")
                )

            extractions = json.loads(json_str)
            if not isinstance(extractions, list):
                extractions = [extractions] if extractions else []

            logger.info(f"[LLM][extract] {file_path}: found {len(extractions)} patterns")
            return extractions

        except Exception as e:
            logger.error(f"[LLM][extract] {file_path} failed: {e}", exc_info=True)
            return []

    @staticmethod
    def build_codebase_context(
        all_extractions: List[dict],
    ) -> CodebaseContext:
        """Combine per-file extractions into a single CodebaseContext.

        Maps the flat extraction dicts into the CodebaseContext schema
        by grouping on instrumentation type.
        """
        from .schemas import GlobalInstrumentation

        http_metrics = []
        db_instrumentation = []
        tracing = []
        error_handling = []
        infra_files = set()

        type_map = {
            "http_metrics": http_metrics,
            "db_instrumentation": db_instrumentation,
            "tracing": tracing,
            "error_handling": error_handling,
            "logging": error_handling,  # logging goes into error_handling bucket
        }

        for ext in all_extractions:
            ext_type = ext.get("type", "")
            target_list = type_map.get(ext_type)
            if target_list is None:
                continue

            target_list.append(GlobalInstrumentation(
                file_path=ext.get("file_path", ""),
                instrumentation_type=ext_type,
                metrics_recorded=ext.get("metrics_recorded", []),
                coverage=ext.get("coverage", ""),
                registration_file=ext.get("registration_file"),
                description=ext.get("description", ""),
            ))

            if ext.get("file_path"):
                infra_files.add(ext["file_path"])
            if ext.get("registration_file"):
                infra_files.add(ext["registration_file"])

        summary_parts = []
        if http_metrics:
            summary_parts.append(f"{len(http_metrics)} HTTP metrics middleware")
        if db_instrumentation:
            summary_parts.append(f"{len(db_instrumentation)} DB instrumentation")
        if tracing:
            summary_parts.append(f"{len(tracing)} tracing setup")
        if error_handling:
            summary_parts.append(f"{len(error_handling)} error/logging handling")

        return CodebaseContext(
            global_http_metrics=http_metrics,
            global_db_instrumentation=db_instrumentation,
            global_tracing=tracing,
            global_error_handling=error_handling,
            infrastructure_files=sorted(infra_files),
            summary=f"Found: {', '.join(summary_parts)}" if summary_parts else "No infrastructure found",
        )

    # ------------------------------------------------------------------
    # Phase C: Gap Verification (backtracking)
    # ------------------------------------------------------------------

    async def verify_gaps(
        self,
        raw_gaps: List[DetectedProblem],
        codebase_context: CodebaseContext,
        callbacks: list = None,
    ) -> Dict[str, VerificationResult]:
        """Verify gaps by backtracking through the codebase.

        For each rule group, one AgentExecutor call with 20 sample gaps.
        Agent reads each gap's source file and traces it back to see if
        infrastructure covers it. Confidence threshold decides the group verdict.
        """
        gaps_by_rule: Dict[str, List[DetectedProblem]] = defaultdict(list)
        for gap in raw_gaps:
            gaps_by_rule[gap.rule_id].append(gap)

        logger.info(
            f"Verifying {len(raw_gaps)} gaps across {len(gaps_by_rule)} rule types "
            f"(sample_size={settings.HEALTH_REVIEW_VERIFICATION_SAMPLE_SIZE}, "
            f"confidence_threshold={settings.HEALTH_REVIEW_VERIFICATION_CONFIDENCE_THRESHOLD})"
        )

        context_text = codebase_context.model_dump_json(indent=2)
        results: Dict[str, VerificationResult] = {}

        for rule_id, gaps in gaps_by_rule.items():
            sample = gaps[:settings.HEALTH_REVIEW_VERIFICATION_SAMPLE_SIZE]

            logger.info(
                f"[LLM][{rule_id}] Verifying {len(sample)} samples "
                f"(of {len(gaps)} total gaps)"
            )

            result = await self._verify_rule_group(
                rule_id=rule_id,
                sample_gaps=sample,
                context_text=context_text,
                callbacks=callbacks,
            )

            # Apply confidence threshold and extend to all gaps
            if len(gaps) > len(sample):
                result = self._extend_verdicts_to_all(result, gaps, rule_id)

            results[rule_id] = result

            # Log per-rule decision
            pass_count = sum(1 for v in result.verdicts if v.verdict in (GapVerdict.FALSE_ALARM, GapVerdict.COVERED_GLOBALLY))
            fail_count = sum(1 for v in result.verdicts if v.verdict == GapVerdict.GENUINE)
            logger.info(
                f"[{rule_id}] Decision: pass={pass_count} fail={fail_count} | "
                f"tool_calls={result.tool_calls_used} | files_read={result.files_read}"
            )

            # Rate limit pause
            if settings.HEALTH_REVIEW_VERIFICATION_DELAY_SECONDS > 0:
                await asyncio.sleep(settings.HEALTH_REVIEW_VERIFICATION_DELAY_SECONDS)

        # Summary
        total_fa = sum(
            sum(1 for v in r.verdicts if v.verdict in (GapVerdict.FALSE_ALARM, GapVerdict.COVERED_GLOBALLY))
            for r in results.values()
        )
        total_genuine = sum(
            sum(1 for v in r.verdicts if v.verdict == GapVerdict.GENUINE)
            for r in results.values()
        )
        logger.info(
            f"Verification complete: genuine={total_genuine} false_alarm={total_fa}"
        )
        return results

    async def _verify_rule_group(
        self,
        rule_id: str,
        sample_gaps: List[DetectedProblem],
        context_text: str,
        callbacks: list = None,
    ) -> VerificationResult:
        """Verify a single rule group's sample gaps using an agent with tools."""
        findings_text = "\n".join(
            f"  {i + 1}. {gap.title} (files: {', '.join(gap.affected_files)})"
            for i, gap in enumerate(sample_gaps)
        )

        user_prompt = VERIFICATION_USER_PROMPT.format(
            codebase_context=context_text,
            rule_id=rule_id,
            count=len(sample_gaps),
            findings=findings_text,
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", VERIFICATION_SYSTEM_PROMPT),
            ("human", "{user_input}"),
            ("placeholder", "{agent_scratchpad}"),
        ])

        agent = create_tool_calling_agent(self.llm, self.tools, prompt)
        executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            max_iterations=200,  # High safety cap; real limit enforced by LLMBudgetCallback
            return_intermediate_steps=True,
            handle_parsing_errors="Output valid JSON array. Default to fail if uncertain.",
            verbose=False,
        )

        invoke_config = {"callbacks": callbacks} if callbacks else {}

        try:
            logger.info(
                f"[LLM][{rule_id}] Invoking verification agent"
            )

            result = await executor.ainvoke(
                {"user_input": user_prompt}, config=invoke_config
            )
            output_text = result.get("output", "[]")

            # Log tool calls
            files_read = []
            intermediate_steps = result.get("intermediate_steps", [])
            for i, step in enumerate(intermediate_steps):
                action = step[0]
                tool_output = step[1] if len(step) > 1 else ""
                tool_name = getattr(action, "tool", "unknown")
                tool_input = getattr(action, "tool_input", "")
                logger.info(
                    f"[LLM][{rule_id}] {tool_name}({tool_input}) → {str(tool_output)[:200]}"
                )
                if tool_name == "read_file":
                    fp = tool_input.get("file_path", "") if isinstance(tool_input, dict) else str(tool_input)
                    files_read.append(fp)

            logger.info(
                f"[LLM][{rule_id}] Agent done: {len(intermediate_steps)} tool calls, "
                f"{len(files_read)} files read: {files_read}"
            )

            # Parse pass/fail verdicts and apply confidence threshold
            verdicts = self._parse_pass_fail_verdicts(
                output_text, sample_gaps, rule_id
            )

            return VerificationResult(
                rule_id=rule_id,
                verdicts=verdicts,
                files_read=files_read,
                tool_calls_used=len(intermediate_steps),
            )

        except Exception as e:
            logger.error(f"Verification failed for {rule_id}: {e}", exc_info=True)
            return VerificationResult(
                rule_id=rule_id,
                verdicts=[
                    GapVerdictResult(
                        gap_title=gap.title,
                        rule_id=rule_id,
                        verdict=GapVerdict.GENUINE,
                        reason=f"Verification failed: {str(e)[:100]}",
                    )
                    for gap in sample_gaps
                ],
            )

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_pass_fail_verdicts(
        self,
        output_text: str,
        gaps: List[DetectedProblem],
        rule_id: str,
    ) -> List[GapVerdictResult]:
        """Parse agent pass/fail output and apply confidence threshold.

        If ≥ threshold of samples pass → group is false_alarm.
        Otherwise → group is genuine.
        """
        json_str = output_text.strip()
        if json_str.startswith("```"):
            lines = json_str.split("\n")
            json_str = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            )

        try:
            raw_verdicts = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning(
                f"[{rule_id}] Failed to parse JSON, defaulting all to genuine. "
                f"Raw: {output_text[:300]}"
            )
            return [
                GapVerdictResult(
                    gap_title=gap.title,
                    rule_id=rule_id,
                    verdict=GapVerdict.GENUINE,
                    reason="Failed to parse verification output",
                )
                for gap in gaps
            ]

        if not isinstance(raw_verdicts, list):
            raw_verdicts = [raw_verdicts]

        # Count pass/fail
        pass_count = 0
        fail_count = 0
        parsed_entries = []
        for raw in raw_verdicts:
            verdict_str = raw.get("verdict", "fail").lower()
            is_pass = verdict_str == "pass"
            if is_pass:
                pass_count += 1
            else:
                fail_count += 1
            parsed_entries.append({
                "gap_title": raw.get("gap_title", ""),
                "is_pass": is_pass,
                "reason": raw.get("reason", ""),
                "evidence_file": raw.get("evidence_file"),
            })

        # Apply confidence threshold
        total = pass_count + fail_count
        threshold = settings.HEALTH_REVIEW_VERIFICATION_CONFIDENCE_THRESHOLD
        group_covered = total > 0 and (pass_count / total) >= threshold

        logger.info(
            f"[{rule_id}] Confidence: {pass_count}/{total} pass "
            f"({pass_count / total * 100:.0f}%) — threshold={threshold * 100:.0f}% → "
            f"{'FALSE_ALARM (group covered)' if group_covered else 'GENUINE (group not covered)'}"
        )

        # Convert to GapVerdictResult
        group_verdict = GapVerdict.FALSE_ALARM if group_covered else GapVerdict.GENUINE
        verdicts = []

        for entry in parsed_entries:
            # Individual gap verdict follows the group decision
            verdicts.append(
                GapVerdictResult(
                    gap_title=entry["gap_title"],
                    rule_id=rule_id,
                    verdict=group_verdict,
                    reason=entry["reason"],
                    evidence_file=entry["evidence_file"],
                )
            )

        # Fill missing verdicts (if agent returned fewer than sample size)
        if len(verdicts) < len(gaps):
            covered_titles = {v.gap_title for v in verdicts}
            for gap in gaps:
                if gap.title not in covered_titles:
                    verdicts.append(
                        GapVerdictResult(
                            gap_title=gap.title,
                            rule_id=rule_id,
                            verdict=group_verdict,
                            reason="No individual verdict from agent, using group decision",
                        )
                    )

        return verdicts

    def _extend_verdicts_to_all(
        self,
        result: VerificationResult,
        all_gaps: List[DetectedProblem],
        rule_id: str,
    ) -> VerificationResult:
        """Extend sample verdicts to all gaps of a rule type.

        The group verdict (from confidence threshold) applies to every gap.
        """
        if not result.verdicts:
            return result

        # Determine the group verdict (should be uniform from _parse_pass_fail_verdicts)
        group_verdict = result.verdicts[0].verdict
        sample_reason = result.verdicts[0].reason
        sample_evidence = result.verdicts[0].evidence_file

        covered_titles = {v.gap_title for v in result.verdicts}
        extended = list(result.verdicts)

        for gap in all_gaps:
            if gap.title not in covered_titles:
                extended.append(
                    GapVerdictResult(
                        gap_title=gap.title,
                        rule_id=rule_id,
                        verdict=group_verdict,
                        reason=f"Extended from sample: {sample_reason}",
                        evidence_file=sample_evidence,
                    )
                )

        logger.info(
            f"[{rule_id}] Extended verdicts from {len(result.verdicts)} samples "
            f"to {len(extended)} gaps (verdict={group_verdict.value})"
        )

        return VerificationResult(
            rule_id=rule_id,
            verdicts=extended,
            files_read=result.files_read,
            tool_calls_used=result.tool_calls_used,
        )

    def _parse_codebase_context(self, output_text: str) -> CodebaseContext:
        """Parse LLM output into a CodebaseContext."""
        json_str = output_text.strip()
        if json_str.startswith("```"):
            lines = json_str.split("\n")
            json_str = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            )

        try:
            raw = json.loads(json_str)
            return CodebaseContext(**raw)
        except Exception as e:
            logger.warning(
                f"Failed to parse CodebaseContext: {e}. Raw: {output_text[:300]}"
            )
            return CodebaseContext(
                summary=f"Parse failed: {str(e)[:200]}",
            )
