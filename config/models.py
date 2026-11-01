from openai import OpenAI
import needle

def get_openai_client():
    return OpenAI(base_url="http://localhost:8080/v1", api_key="not-needed")

def get_needle_model(tools):
    return needle.Needle(tools=tools, stateless=True)