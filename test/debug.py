from groq import Groq
import os
client = Groq(
    api_key=os.environ.get("GROQ_API_KEY"),
)
print(os.environ.get("GROQ_API_KEY"))
chat_completion = client.chat.completions.create(
    messages=[
        {
            "role": "user",
            "content": "Explain the importance of fast language models",
        }
    ],
    model="llama-3.3-70b-versatile",
    stream=False,
)

print(chat_completion.choices[0].message.content)