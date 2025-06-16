from dotenv import load_dotenv
import os


load_dotenv()

test = os.getenv("TEST")

print(f"{test}")