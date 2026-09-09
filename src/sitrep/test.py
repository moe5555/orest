from ollama import chat

r = chat(model='gemma4:12b-it-qat',
         messages=[{'role': 'user', 'content': "Describe the image and transcribe the audio", 'images': ["src/data/test_frame.jpg"] + ["src/data/test01_20s.wav"]}],
         think=False,
         keep_alive=-1,
         options={'num_ctx': 8192, 'num_predict': 400, 'temperature': 0.2})


print(r.message.content)