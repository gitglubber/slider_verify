from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application configuration using pydantic-settings."""

    # Slide API
    slide_api_key: str = Field(..., alias="SLIDE_API_KEY")
    slide_api_base_url: str = Field(
        default="https://api.slide.tech",
        alias="SLIDE_API_BASE_URL"
    )

    # OpenAI-Compatible LLM
    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    openai_api_base_url: str = Field(
        default="https://api.openai.com/v1",
        alias="OPENAI_API_BASE_URL"
    )
    openai_model: str = Field(
        default="gpt-4-turbo-preview",
        alias="OPENAI_MODEL"
    )

    # VM Configuration
    vm_boot_timeout: int = Field(default=300, alias="VM_BOOT_TIMEOUT")
    vm_operation_timeout: int = Field(default=60, alias="VM_OPERATION_TIMEOUT")
    vm_login_screen_timeout: int = Field(default=120, alias="VM_LOGIN_SCREEN_TIMEOUT")

    # Windows Server Credentials
    windows_username: str = Field(default="Administrator", alias="WINDOWS_USERNAME")
    windows_password: str = Field(..., alias="WINDOWS_PASSWORD")

    # Report Configuration
    report_output_dir: str = Field(default="reports", alias="REPORT_OUTPUT_DIR")
    screenshot_dir: str = Field(default="screenshots", alias="SCREENSHOT_DIR")

    class Config:
        env_file = ".env"
        case_sensitive = False


def get_settings() -> Settings:
    """Get application settings."""
    return Settings()
