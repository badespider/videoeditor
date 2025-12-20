"""
Script to list available Gemini models for your API key.
Run this to find the correct model name string.

Usage:
    GEMINI_API_KEY=your_key python list_models.py
    
Or set the key in the script directly (not recommended for production).
"""

import os
import google.generativeai as genai

# Get API key from environment
api_key = os.environ.get("GEMINI_API_KEY")

if not api_key:
    print("ERROR: GEMINI_API_KEY environment variable not set")
    print("Run with: GEMINI_API_KEY=your_key python list_models.py")
    exit(1)

genai.configure(api_key=api_key)

print("--- YOUR AVAILABLE MODELS ---")
print("(Only showing models that support generateContent)\n")

try:
    models_found = []
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            models_found.append(m.name)
            print(f"Name: {m.name}")
            if hasattr(m, 'display_name'):
                print(f"  Display: {m.display_name}")
            if hasattr(m, 'description'):
                print(f"  Desc: {m.description[:100]}...")
            print()
    
    print(f"\n--- SUMMARY ---")
    print(f"Found {len(models_found)} models that support generateContent")
    
    # Highlight Pro models for video
    print("\n--- RECOMMENDED FOR VIDEO ---")
    for name in models_found:
        if 'pro' in name.lower() and '1.5' in name:
            print(f"  {name}")
            
except Exception as e:
    print(f"Error: {e}")

