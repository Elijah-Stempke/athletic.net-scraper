import csv
import glob

output_file = "1merged.csv"

# Get all CSV files in the current directory except the output
csv_files = [f for f in glob.glob("*.csv") if f != output_file]
csv_files.sort()

header_saved = False

with open(output_file, "w", newline="", encoding="utf-8") as outfile:
    writer = None

    for file in csv_files:
        with open(file, "r", newline="", encoding="utf-8") as infile:
            reader = csv.reader(infile)

            header = next(reader)

            if not header_saved:
                writer = csv.writer(outfile)
                writer.writerow(header)
                header_saved = True

            for row in reader:
                writer.writerow(row)

print(f"Merged {len(csv_files)} files into {output_file}")