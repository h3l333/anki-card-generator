import json
import csv
from pathlib import Path
from datasets import MAX_ITEMS, REQUIRED_ITEM_KEY

_CSV_FILES_PATH = Path(__name__).resolve().parent / "csv_data"
    
def read_and_parse_csv(filePath, encoding) -> list[dict[str, str]]:
    with open(file=filePath, mode="r", newline="", encoding=encoding) as csv_file:
        reader = csv.reader(csv_file)
        data_list = list(reader)
        return data_list
    
print(read_and_parse_csv(_CSV_FILES_PATH / "csv_test.csv", "utf-8"))
