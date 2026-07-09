import ollama

MODEL = "llama3.2" 

def generate(system_prompt: str, user_message: str) -> str:
    response = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
    )
    return response["message"]["content"]