conda env create -f environment.yml
conda activate agentic-framework

ollama serve &
ollama pull llama3.2

python main.py