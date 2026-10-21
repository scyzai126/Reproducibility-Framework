from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    OPENAI_API_KEY: str
    MYSQL_URL: str = "mysql+aiomysql://immport_user@localhost:3306/immport_dr62"
    OPENAI_MODEL: str = "gpt-5.4"
    #: How round 4 (assay -> OBI) finds its term once the exact name lookup has not answered:
    #: "embedding" (the default) retrieves top-K by vector similarity and picks once;
    #: "descend" walks the OBI assay tree top-down, one chat call per level, choosing among a
    #: term's direct children (it lost to embedding on the three-paper comparison,
    #: docs/obi_descent_vs_embedding_3papers.md); "hybrid" is the embedding pick followed by one
    #: descent from it when the picked term has children, under evaluation. Set either in .env
    #: to run it; neither is the default until it beats embedding on the curated benchmark.
    OBI_MAPPING_STRATEGY: str = "embedding"
    IMMPORT_BASE_URL: str = "https://www.immport.org"
    IMMPORT_USERNAME: str = ""
    IMMPORT_PASSWORD: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
