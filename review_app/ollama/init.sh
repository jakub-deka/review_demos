#!/usr/bin/env bash

ollama serve &
ollama list
ollama pull nomic-embed-text

ollama server &
ollama list
ollama pull mxbai-embed-large

ollama serve &
ollama list
ollama pull llama3:instruct