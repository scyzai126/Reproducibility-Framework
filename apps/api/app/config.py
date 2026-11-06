from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    OPENAI_API_KEY: str
    MYSQL_URL: str = "mysql+aiomysql://immport_user@localhost:3306/immport_dr62"
    OPENAI_MODEL: str = "gpt-5.4"
    # Retries the OpenAI SDK makes on a rate limit, a connection error or a 5xx before the
    # call fails. The SDK's own default is 2. The assay chain turns a call that fails after
    # its retries into a soft loss -- a skipped round, an ERROR record -- rather than a crash,
    # so over a corpus a short budget shows up as silently poorer registries, not as errors.
    OPENAI_MAX_RETRIES: int = 5
    IMMPORT_BASE_URL: str = "https://www.immport.org"
    IMMPORT_USERNAME: str = ""
    IMMPORT_PASSWORD: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
