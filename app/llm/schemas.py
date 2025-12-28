"""
Pydantic schemas for BYOLLM (Bring Your Own LLM) configuration.

These schemas handle:
- API request/response validation
- Secure API key handling (never returned in responses)
- Provider-specific configuration validation
"""

from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict


# Provider type literals for type checking
LLMProviderType = Literal["vibemonitor", "openai", "azure_openai", "gemini"]
LLMStatusType = Literal["active", "error", "unconfigured"]


class LLMConfigResponse(BaseModel):
    """
    Response schema for LLM configuration.

    IMPORTANT: This schema intentionally excludes API keys for security.
    The has_custom_key field indicates whether a custom key is configured.
    """

    provider: LLMProviderType
    model_name: Optional[str] = None
    status: LLMStatusType
    last_verified_at: Optional[datetime] = None
    last_error: Optional[str] = None
    has_custom_key: bool = Field(
        description="True if config_encrypted is not empty/null (API key is configured)"
    )
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class LLMConfigCreate(BaseModel):
    """
    Schema for creating/updating LLM configuration.

    API keys are accepted here but NEVER returned in responses.
    """

    provider: LLMProviderType = Field(
        description="LLM provider: vibemonitor (default), openai, azure_openai, or gemini"
    )
    model_name: Optional[str] = Field(
        None,
        description="Model name (e.g., 'gpt-4-turbo', 'gemini-1.5-pro'). If not specified, uses provider default.",
        max_length=100,
    )

    # API Key - NEVER returned in responses, only accepted on create/update
    api_key: Optional[str] = Field(
        None,
        description="API key for the provider. Required for all providers except 'vibemonitor'.",
    )

    # Azure OpenAI-specific fields
    azure_endpoint: Optional[str] = Field(
        None,
        description="Azure OpenAI endpoint URL (e.g., 'https://your-resource.openai.azure.com/'). Required for azure_openai.",
    )
    azure_api_version: Optional[str] = Field(
        "2024-02-01",
        description="Azure OpenAI API version. Defaults to '2024-02-01'.",
    )
    azure_deployment_name: Optional[str] = Field(
        None,
        description="Azure OpenAI deployment name. Required for azure_openai.",
    )


class LLMConfigUpdate(BaseModel):
    """
    Schema for updating LLM configuration (partial updates allowed).
    """

    provider: Optional[LLMProviderType] = Field(
        None,
        description="LLM provider to switch to",
    )
    model_name: Optional[str] = Field(
        None,
        description="Model name to use",
        max_length=100,
    )

    # API Key - for updating the key
    api_key: Optional[str] = Field(
        None,
        description="New API key for the provider",
    )

    # Azure OpenAI-specific fields
    azure_endpoint: Optional[str] = Field(
        None,
        description="Azure OpenAI endpoint URL",
    )
    azure_api_version: Optional[str] = Field(
        None,
        description="Azure OpenAI API version",
    )
    azure_deployment_name: Optional[str] = Field(
        None,
        description="Azure OpenAI deployment name",
    )


class LLMVerifyRequest(BaseModel):
    """
    Schema for verifying LLM provider credentials before saving.
    """

    provider: LLMProviderType = Field(description="LLM provider to verify")
    model_name: Optional[str] = Field(
        None,
        description="Model name to test",
    )
    api_key: Optional[str] = Field(
        None,
        description="API key to verify. Required for all providers except 'vibemonitor'.",
    )

    # Azure-specific
    azure_endpoint: Optional[str] = None
    azure_api_version: Optional[str] = "2024-02-01"
    azure_deployment_name: Optional[str] = None


class LLMVerifyResponse(BaseModel):
    """
    Response schema for LLM credential verification.
    """

    success: bool = Field(description="Whether the credentials are valid and working")
    error: Optional[str] = Field(
        None, description="Error message if verification failed"
    )
    model_info: Optional[dict] = Field(
        None,
        description="Optional model information (e.g., available models, context window)",
    )
