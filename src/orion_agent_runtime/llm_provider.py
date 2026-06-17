from openai import OpenAI

# 这里直接初始化了一个 OpenAI 客户端，后续可以改成工厂模式，根据配置创建不同的 LLM 客户端。

client = OpenAI(
    base_url="http://localhost:1234/v1",
    api_key="local-1234567890abcdef"
)

MODEL_NAME = "local-model"