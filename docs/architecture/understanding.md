# Kya-Ray — Complete Project Brief for Beginners

## 1. What is Kya-Ray?

Kya-Ray is a **context-aware AI desktop assistant** that helps users understand or work with text without switching between applications.

Imagine you're reading something in a PDF, browsing a website, writing code, or studying a difficult concept. Normally, you'd copy the text, open ChatGPT, paste it, and ask a question.

Kya-Ray simplifies this process.

**You select the text, press `Ctrl + Shift + J`, and Kya-Ray displays an AI-generated response in a small floating window.**

That's the core idea.

## 2. What problem does it solve?

People frequently encounter information they don't understand while working on their computers.

For example:
- A student encounters a difficult technical term while studying.
- A programmer encounters an unfamiliar line of code.
- Someone reading an article wants a quick summary.
- A user wants help creating something from selected text.

The usual process involves switching applications and repeatedly copying and pasting information.

Kya-Ray aims to make this interaction faster and more convenient by bringing AI assistance directly to the user's workflow.

## 3. What are its main features?

### A. Global keyboard shortcut

Kya-Ray uses `Ctrl + Shift + J` to trigger its main action.

A global shortcut can be used while another application is active, so users don't need to open Kya-Ray every time they need help.

### B. Text selection and capture

The user selects text in another application. Kya-Ray captures that text and uses it as context for the AI request.

The selected text is the input; the generated answer is the output.

### C. Four intelligent actions

Kya-Ray uses four internal intent labels to guide the type of response it generates.

- **Explain (`-explain`):** Explains selected text in simple language.
- **Summarize (`-summarize`):** Condenses longer text into its main points.
- **Code (`-code`):** Helps explain code and identify possible syntax errors or typos.
- **Create (`-create`):** Helps generate content based on the selected context.

The application uses rules and patterns to infer the intended action. These labels are internal instructions, not four separate AI models.

### D. Floating interface

The response appears in a floating window rather than requiring the user to switch to another application.

The prototype supports displaying, moving, and dismissing the window.

The goal is to make the interface unobtrusive so users can return to their work quickly.

### E. Local AI processing

Kya-Ray connects to a locally running AI model through Ollama.

The current model is `llama3.2:1b`.

This means the model runs on the user's own computer rather than requiring every request to be sent to a cloud-based AI provider.

The application still needs Ollama and the model installed and running. Local processing also does not automatically guarantee that every part of an application is private; clipboard handling and other application behavior must be considered.

---

## 4. How does Kya-Ray work?

Think of it as a chain of six steps.

**Step 1: The user selects text.**

For example, the user selects the term “CAP theorem” while studying.

**Step 2: The user presses the shortcut.**

They press `Ctrl + Shift + J`.

**Step 3: Kya-Ray captures the text.**

The current implementation uses keyboard automation to copy the selected text into the clipboard and read it. It also attempts to restore the previous clipboard contents afterward.

**Step 4: Kya-Ray identifies the intended action.**

The intent-classification logic examines the selected text and chooses an action such as `-explain` or `-code`.

**Step 5: The AI generates a response.**

Kya-Ray sends the text and the appropriate instructions to the local Ollama API. The language model generates the response.

**Step 6: The answer appears in the floating window.**

The user reads the response and returns to their work.

In short:

`Text Selection → Keyboard Shortcut → Text Capture → Intent Detection → Local AI → Floating Response`

---

## 5. What technologies are used?

You should understand what each technology does, not just memorize its name.

### Python — the main programming language

Python is used to write the application's main logic.

It coordinates keyboard input, text capture, intent classification, communication with the AI model, and the user interface.

Think of Python as the language used to connect all the parts.

### Tkinter — the user interface

Tkinter is a GUI library included with Python.

GUI stands for *Graphical User Interface* — the visible part of an application that users interact with.

Kya-Ray uses Tkinter to create its floating response window, buttons, and other interface elements.

### pynput — keyboard monitoring and automation

`pynput` allows Python to listen for keyboard events and simulate keyboard input.

Kya-Ray uses it to detect the global shortcut and help capture selected text.

### pyperclip — clipboard access

The clipboard is the temporary place where copied text is stored.

`pyperclip` lets the application read and write clipboard text. Kya-Ray uses this to obtain the selected text through a copy operation.

### Ollama — local AI runtime

Ollama is software that allows language models to run locally on a computer and exposes an API that applications can use.

Kya-Ray sends a request to Ollama running on the same computer.

### Llama 3.2 1B — the language model

A language model is an AI system trained to understand and generate text.

The `1B` in the model name refers to approximately one billion parameters. Parameters are learned numerical values that help the model generate responses.

Kya-Ray uses this model to explain, summarize, and work with the captured text.

**Important distinction:** Ollama is the software that runs and serves the model. Llama is the model that generates the response. They are not the same thing.

---

## 6. How do the technical components communicate?

Imagine a restaurant.

- The user places an order.
- The application receives it.
- The application prepares the request.
- The AI model processes it.
- The application serves the result.

Technically, Kya-Ray sends an HTTP request to Ollama's local API endpoint:

`http://127.0.0.1:11434/api/generate`

Here is what the important terms mean:

- **HTTP:** A standard way for software applications to communicate.
- **API:** An interface that allows one program to request services from another.
- **Localhost (`127.0.0.1`):** An address referring to the same computer.
- **Port (`11434`):** A numbered communication endpoint used by Ollama.
- **JSON:** A structured format used to send information, such as the prompt and model settings, in the request.

Kya-Ray sends the selected text and instructions in the request. Ollama returns the generated response, which Kya-Ray displays.

This communication is local when it is sent to the local Ollama instance, although that alone does not establish the privacy behavior of every dependency.

---

## 7. What is intent classification?

Intent classification means determining what a user wants to accomplish.

Consider these examples:

- “What does this concept mean?” → Explain.
- A long passage of text → Possibly summarize.
- A Python import statement → Possibly code assistance.
- Selected notes used to draft an email → Possibly create.

Kya-Ray uses deterministic rules and patterns to infer the intent rather than asking the user to choose from a menu every time.

The advantage is speed and simplicity.

The limitation is that rules cannot understand every possible situation. For example, a mathematical formula inside a paragraph might be mistaken for code.

The current classifier is a heuristic system, so its decisions need testing and improvement.

## 8. What makes the application responsive?

AI generation can take several seconds. If the application waited for every AI request on its main interface thread, the window could become unresponsive.

Kya-Ray uses background worker threads to perform work such as requesting AI responses.

It uses a thread-safe queue to communicate results back to the Tkinter interface, which updates the window on its own main thread.

In simple terms, the interface can continue operating while the AI works in the background.

## 9. How is the application tested?

The project has automated unit tests.

A unit test checks a small part of the application independently. For example:

- Whether a text selection is classified as code or an explanation.
- Whether ordinary prose avoids false code classification.
- Whether the floating window's geometry calculations behave as expected.
- Whether certain error-handling and response-processing functions work correctly.

The latest recorded test run passed 41 tests.

However, passing unit tests does not guarantee that the AI's answers are factually correct. The application also needs manual testing and real-world evaluation of generated responses.

## 10. What are the current limitations?

Every real project has limitations. Understanding them makes your explanation more credible.

**1. AI accuracy:** The model sometimes generates incorrect or misleading explanations.

**2. Intent detection:** Rule-based classification can choose the wrong action for ambiguous text.

**3. Hardware requirements:** Local inference uses the computer's memory and processing resources.

**4. Runtime dependency:** The current prototype requires Ollama and the model to be installed and available.

**5. Clipboard dependency:** Text capture depends on simulated copying, which can behave differently across applications.

**6. Packaging:** A standalone Windows distribution and a complete first-run installation experience are still being developed.

Do not claim these issues have been completely solved. Explain that they are areas for improvement.

---

## 11. Common viva questions and simple answers

**Q1. What is Kya-Ray?**

Kya-Ray is a context-aware desktop AI assistant that allows users to select text, press a keyboard shortcut, and receive a contextual response in a floating window.

**Q2. Why did you develop it?**

To reduce the friction of switching between applications whenever a user needs help understanding or working with selected text.

**Q3. Why did you choose Python?**

Python provides libraries for keyboard automation, clipboard access, GUI development, and communication with AI services. It lets us connect these functions without building everything from scratch.

**Q4. What is the role of Tkinter?**

Tkinter creates and manages the graphical interface, including the floating response window.

**Q5. Why use Ollama?**

Ollama provides a convenient way to run a language model locally and access it through an API.

**Q6. What is an LLM?**

An LLM, or large language model, is an AI model trained to process and generate human-like text.

**Q7. Why use a local model?**

Local inference can reduce dependence on cloud AI services and allow text to be processed on the user's computer. It also avoids per-request cloud API charges, although the user still needs suitable hardware and the required software.

**Q8. What is an API?**

An API is a defined way for one software component to communicate with another. Kya-Ray uses Ollama's API to request AI-generated responses.

**Q9. What is the difference between the model and Ollama?**

The model generates the text. Ollama runs the model and provides the interface through which Kya-Ray communicates with it.

**Q10. How does Kya-Ray know what kind of response to generate?**

It uses intent-classification rules to infer whether the selected text needs an explanation, summary, code-related response, or generated content. The chosen intent is included in the instructions sent to the model.

**Q11. What happens if Ollama is not running?**

Kya-Ray cannot obtain a response from the local model. The application must handle the connection error and guide the user to start or install the required software.

**Q12. Is Kya-Ray completely accurate?**

No. The language model can make mistakes, so generated responses should be evaluated rather than assumed to be correct.

**Q13. How do you prevent the interface from freezing?**

The application performs time-consuming AI requests in background threads and uses a queue to communicate results to the Tkinter interface.

**Q14. What is the biggest limitation of the current system?**

Response reliability. The system can generate incorrect answers, and intent classification can occasionally misidentify the selected text.

**Q15. What improvements are planned?**

A minimal interface, more reliable intent classification and responses, better error handling, and a straightforward Windows installation and distribution process.

---

## 12. What you must understand before presenting

If you remember only these points, remember these:

1. **Kya-Ray is the application; Python is its main programming language.**
2. **Tkinter creates the UI.**
3. **pynput handles keyboard monitoring and automation.**
4. **pyperclip helps capture text through the clipboard.**
5. **Ollama runs the local model and exposes an API.**
6. **Llama 3.2 1B generates the AI response.**
7. **Intent classification decides which instructions to use.**
8. **Background threads keep the interface responsive.**
9. **The system is a working prototype, not yet a fully packaged public release.**
10. **The AI can make mistakes; honest discussion of limitations is part of a good technical presentation.**

### The best way to explain the entire project

“Kya-Ray is a Python-based desktop AI assistant. When the user selects text and presses a global keyboard shortcut, the application captures the text, determines the likely intent, and sends a suitable prompt to a locally running language model through Ollama. The generated response is then displayed in a floating Tkinter window. Our goal is to make AI assistance faster and more convenient without requiring users to switch applications.”

Understand this explanation, and the rest of the project becomes much easier to follow.