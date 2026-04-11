from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    OPENAI_API_KEY: str
    MYSQL_URL: str = "mysql+aiomysql://immport_user@localhost:3306/immport_dr62"
    OPENAI_MODEL: str = "gpt-5.4"
    IMMPORT_BASE_URL: str = "https://www.immport.org"
    IMMPORT_USERNAME: str = ""
    IMMPORT_PASSWORD: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
