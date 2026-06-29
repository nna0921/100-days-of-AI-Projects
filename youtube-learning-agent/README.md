# YouTube Learning Agent

An intelligent FastAPI application that transforms YouTube videos into comprehensive study materials using Google's Gemini AI and Gmail integration.

## Overview

The YouTube Learning Agent automatically processes YouTube video transcripts and generates structured study materials including notes, summaries, quizzes, and flashcards. It can also email these materials directly to recipients, making it perfect for students and learners who want to optimize their study workflow.

## Features

- **📺 YouTube Transcript Extraction** — Automatically fetches and processes video transcripts
- **🤖 AI-Powered Study Materials** — Uses Google Gemini 2.5 Flash to generate:
  - Structured notes organized by topic
  - Concise summaries (3-5 sentences)
  - Quiz questions with answer keys
  - Flashcard pairs for spaced repetition
- **📧 Gmail Integration** — Automatically send study materials via email
- **⚡ Fast & Efficient** — Built with FastAPI for high performance
- **🐳 Docker Ready** — Containerized deployment support

## Prerequisites

- Python 3.10+
- Google Gemini API key
- Gmail OAuth credentials (optional, for email functionality)
- YouTube Transcript API access

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/nna0921/100-days-of-AI-Projects.git
   cd 100-days-of-AI-Projects/youtube-learning-agent