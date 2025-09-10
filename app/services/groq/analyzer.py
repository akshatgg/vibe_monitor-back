# app/services/groq/analyzer.py
import os
import json
import zipfile
import tempfile
from datetime import datetime
from groq import Groq
from typing import Dict, Any, Optional
from pydantic import BaseModel
from pathlib import Path

class GroqAnalysisResult(BaseModel):
    root_cause: str
    location: str
    why: str
    fix_steps: list[str]
    confidence: float
    files_involved: list[str]
    commit: str = "recent"
    author: str = "system"

class GroqAnalyzer:
    def __init__(self):
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.model = "llama-3.3-70b-versatile"
        
    def _compress_codebase(self) -> str:
        """Compress the codebase into a temporary zip file and return its contents as text"""
        try:
            # Create a temporary file for the zip
            with tempfile.NamedTemporaryFile(mode='w+b', suffix='.zip', delete=False) as tmp_file:
                zip_path = tmp_file.name
                
            # Create zip with relevant files
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                codebase_root = Path(self.codebase_path)
                
                # Include key files for analysis
                files_to_include = [
                    "index.js",
                    "observe.js", 
                    "package.json",
                    "*.js",
                    "*.ts",
                    "*.json"
                ]
                
                for file_pattern in files_to_include:
                    for file_path in codebase_root.glob(file_pattern):
                        if file_path.is_file():
                            arcname = file_path.relative_to(codebase_root)
                            zipf.write(file_path, arcname)
            
            # Read the files as text instead of binary for LLM analysis
            file_contents = []
            with zipfile.ZipFile(zip_path, 'r') as zipf:
                for file_info in zipf.filelist:
                    if not file_info.filename.endswith('/'):  # Skip directories
                        try:
                            with zipf.open(file_info.filename) as f:
                                content = f.read().decode('utf-8')
                                file_contents.append(f"=== {file_info.filename} ===\n{content}\n")
                        except UnicodeDecodeError:
                            file_contents.append(f"=== {file_info.filename} ===\n[Binary file - skipped]\n")
            
            # Clean up temp file
            os.unlink(zip_path)
            
            return "\n".join(file_contents)
            
        except Exception as e:
            print(f"Failed to compress codebase: {e}")
            return "Error: Could not read codebase files"
    
    def _build_analysis_prompt(self, error_data: Dict[str, Any], trace_data: Optional[Dict], metrics_data: Optional[Dict]) -> str:
        """Build the prompt for Groq analysis"""
        
        # Extract key error information
        error_message = error_data.get('message', 'Unknown error')
        error_type = error_data.get('error_type', 'Unknown')
        endpoint = error_data.get('endpoint', 'Unknown')
        status_code = error_data.get('status_code', 'Unknown')
        
        # Get codebase context
        codebase_content = self._compress_codebase()
        
        prompt = f"""You are an expert Node.js/Express.js developer analyzing a production error. Your task is to perform root cause analysis and provide actionable fix suggestions.

## Error Details
- **Error Type**: {error_type}
- **Status Code**: {status_code}
- **Endpoint**: {endpoint}
- **Error Message**: {error_message}
- **Timestamp**: {error_data.get('timestamp', 'Unknown')}

## Trace Data Available
{json.dumps(trace_data, indent=2) if trace_data else 'No trace data available'}

## Metrics Data Available
{json.dumps(metrics_data, indent=2) if metrics_data else 'No metrics data available'}

## Application Codebase
{codebase_content}

## Analysis Requirements
Please analyze this error and provide a structured response with:

1. **Root Cause**: What exactly caused this error?
2. **Location**: Which file and line number (if identifiable)?
3. **Why**: Explain the technical reason for the failure
4. **Fix Steps**: Provide 3-5 specific actionable steps to resolve this
5. **Confidence**: Rate your confidence in this analysis (0.0-1.0)
6. **Files Involved**: List the files that need to be modified

## Response Format
Respond with a valid JSON object in this exact format:
```json
{{
    "root_cause": "Clear description of the root cause",
    "location": "filename:line_number or 'unknown' if not determinable",
    "why": "Technical explanation of why this error occurred",
    "fix_steps": [
        "Step 1: Specific action to take",
        "Step 2: Another specific action",
        "Step 3: Additional action if needed"
    ],
    "confidence": 0.85,
    "files_involved": ["index.js", "other_file.js"]
}}
```

Focus on practical, implementable solutions. Consider Express.js best practices, error handling patterns, and Node.js conventions."""

        return prompt
    
    def analyze_error(self, error_data: Dict[str, Any], trace_data: Optional[Dict] = None, metrics_data: Optional[Dict] = None) -> GroqAnalysisResult:
        """Perform AI-powered root cause analysis on the error"""
        
        try:
            # Build the analysis prompt
            prompt = self._build_analysis_prompt(error_data, trace_data, metrics_data)
            
            print("🤖 Starting Groq AI analysis...")
            
            # Call Groq API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system", 
                        "content": "You are an expert software engineer specializing in Node.js error analysis. Always respond with valid JSON only."
                    },
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                temperature=0.1,  # Low temperature for consistent analysis
                max_tokens=2048
            )
            
            # Parse the response
            analysis_text = response.choices[0].message.content.strip()
            
            # Extract JSON from response (in case there's extra text)
            json_start = analysis_text.find('{')
            json_end = analysis_text.rfind('}') + 1
            
            if json_start != -1 and json_end != -1:
                json_content = analysis_text[json_start:json_end]
                analysis_data = json.loads(json_content)
            else:
                raise ValueError("No valid JSON found in response")
            
            # Create result object with fallbacks
            result = GroqAnalysisResult(
                root_cause=analysis_data.get('root_cause', 'Unable to determine root cause'),
                location=analysis_data.get('location', 'unknown'),
                why=analysis_data.get('why', 'Analysis incomplete'),
                fix_steps=analysis_data.get('fix_steps', ['Review error logs', 'Check application code']),
                confidence=float(analysis_data.get('confidence', 0.5)),
                files_involved=analysis_data.get('files_involved', ['unknown']),
                commit="recent",
                author="system"
            )
            
            print(f"✅ Groq analysis completed with {result.confidence:.0%} confidence")
            return result
            
        except Exception as e:
            print(f"❌ Groq analysis failed: {e}")
            
            # Return fallback analysis
            return GroqAnalysisResult(
                root_cause=f"AI analysis failed: {str(e)}",
                location="unknown",
                why="Unable to perform automated analysis due to service error",
                fix_steps=[
                    "Review error logs manually",
                    "Check application health",
                    "Verify service dependencies"
                ],
                confidence=0.1,
                files_involved=["unknown"],
                commit="unknown",
                author="system"
            )

# Global instance
groq_analyzer = GroqAnalyzer()