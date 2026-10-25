## Adding new things I come across

1. 74 is the Windows virtual key code for 'J' (ord('J'))

2. What is Ollama?
Think of Ollama as a local AI server engine for your computer. Normally, when using AI (like ChatGPT or Claude), your computer sends text across the internet to massive cloud servers. Ollama allows you to run modern language models directly on your own hardware without needing internet access, cloud accounts, or API keys.

3. What is a Local Model?
A model (such as Meta's llama3.2 or Microsoft's phi3) is a pre-trained neural network file (typically 1 GB to 4 GB for compact desktop models).

4. What is an API Request?
An API (Application Programming Interface) request is simply a structured message sent from one program to another.

5. How to calculate tokens per second?
Ollama gives us the generated token count and generation duration. We can calculate tokens per second:
\[
\text{Tokens/sec}=\frac{\text{eval\_count}}{\text{eval\_duration in seconds}}
\]