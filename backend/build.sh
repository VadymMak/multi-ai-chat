#!/usr/bin/env bash
pip install --upgrade pip
pip install --upgrade setuptools wheel
pip install tiktoken==0.7.0  # Updated for GPT-4o tokenizer support
pip install -r requirements.txt