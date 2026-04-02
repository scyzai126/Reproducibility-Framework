from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    OPENAI_API_KEY: str
    MYSQL_URL: str = "mysql+aiomysql://cs2635:Edic-123@localhost:3306/claim_reproduce"
    OPENAI_MODEL: str = "gpt-5.4"
    IMMPORT_BASE_URL: str = "https://www.immport.org"
    IMMPORT_USERNAME: str = ""
    IMMPORT_PASSWORD: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
