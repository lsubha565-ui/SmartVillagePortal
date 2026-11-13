# 🏛️ Chatbot Enabled Smart Village Service Portal

A web portal built with Python (Flask) and MySQL to help village citizens easily report civic problems, apply for birth and death certificates, and get instant help from an AI chatbot[cite: 2, 10].

---

## 📌 Project Description

In many villages, people have to visit the Panchayat office multiple times to report problems like broken streetlights or water issues, or to apply for birth and death certificates. They often do not know which documents are required.

The **Smart Village Service Portal** solves this problem by bringing these services online. Villagers can submit complaints with photos, apply for certificates, and check their application status from their phone or computer. It also includes a smart AI chatbot that answers questions in simple English and Tanglish, along with an Admin Dashboard for village officers to verify documents and approve requests.

**Project Coverage:** Tirunelveli District (Palayamkottai, Tirunelveli, and Ambasamudram Taluks).

---

## 🚀 Key Features

* **Online Complaint Registration:** Report issues like drinking water, street lights, damaged roads, and drainage with location details and photo proof. Generates a unique tracking ID (e.g., `CMP1001`).
* **Birth & Death Certificate Applications:** Apply online by entering basic details and uploading hospital reports or ID proofs.
* **Smart AI Chatbot (English & Tanglish):** 
  * Gives instant answers from a built-in dataset of 200 common questions[cite: 5, 10].
  * Uses **Google Gemma 2 AI** (via OpenRouter API) to understand and reply to everyday Tanglish questions.
* **Live Status Tracking:** Citizens can log in anytime to check if their complaint or certificate is *Pending*, *In Review*, or *Approved*.
* **Admin Dashboard:** Village officers can view all requests, check uploaded documents, and update the status with one click.
* **Secure Login:** Passwords are encrypted safely, and user sessions are protected.

---
## 🛠️ Tech Stack

| Layer | Technology / Tool |
| :--- | :--- |
| **Backend Framework** | Python 3, Flask |
| **Database** | MySQL (Relational Schema with Foreign-Key Referential Integrity) |
| **AI & NLP** | Google Gemma 2 9B (via OpenRouter API), Sequence Similarity Matching |
| **Frontend** | HTML5, CSS3, JavaScript (Fetch API), Jinja2 Templating |
| **Security & Utilities** | Werkzeug (Password Hashing), Python `requests`, `os` environment variables |
| **Local Environment** | XAMPP (Apache & MySQL), Windows PowerShell |

---
---

