# Code Plagiarism Checker

C++ plagiarism detector using Tree-sitter AST parsing. Structurally normalizes code so renamed variables don't fool it. MongoDB storage with tag-based batch comparison to check all class submissions against each other.

## How It Works

The tool parses C++ code into an Abstract Syntax Tree, then normalizes it by replacing all identifiers with a generic `ID` token. This means code that's copied and has variables renamed will still produce identical normalized output:

```cpp
// Original                          // "Disguised" copy
map<string, vector<Rule>> nt_rules;  map<string, vector<Rule>> rulesByNT;
for (const auto& rule : rules) {     for (const auto& r : rules) {
    nt_rules[rule.lhs].push_back(rule);  rulesByNT[r.lhs].push_back(r);
}                                    }

// Both normalize to:
map<string, vector<ID>> ID;
for (const auto& ID : ID) {
    ID[ID.ID].push_back(ID);
}
```

Similarity is calculated using SequenceMatcher on the normalized code.

## Features

- **Structural comparison** — Catches plagiarism even when variables are renamed
- **Tag-based organization** — Group submissions by class/assignment (e.g., `cse330-hw5`)
- **Batch analysis** — Compare all submissions against each other with one click
- **Suspicious pattern detection** — Flags identical string literals and code blocks
- **Web interface** — Easy-to-use frontend for all operations

## Installation

### Prerequisites

- Python 3.8+
- MongoDB

### Setup

```bash
# Clone the repo
git clone https://github.com/yourusername/plagiarism-checker.git
cd plagiarism-checker

# Install dependencies
pip install -r requirements.txt

# Start MongoDB (if not running)
mongod

# Run the server
python server.py
```

Open `frontend.html` in your browser.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_URI` | `mongodb://localhost:27017` | MongoDB connection string |

## Usage

### Web Interface

The frontend has five tabs:

1. **Quick Compare** — Paste two code samples for instant comparison
2. **Submit Code** — Add code to the database with a tag and student ID
3. **Check Against Tag** — Check one submission against all others with the same tag
4. **Batch Analysis** — Compare all submissions with a tag against each other
5. **Manage Tags** — View and delete submissions

### API Endpoints

#### Compare Two Code Samples
```bash
POST /api/check
Content-Type: application/json

{
  "code1": "int main() { ... }",
  "code2": "int main() { ... }"
}
```

#### Submit Code
```bash
POST /api/submit
Content-Type: application/json

{
  "code": "int main() { ... }",
  "tag": "cse330-hw5",
  "student_id": "1234567890",
  "filename": "main.cpp"
}
```

#### Check Against All Submissions with Tag
```bash
POST /api/check_against_tag
Content-Type: application/json

{
  "code": "int main() { ... }",
  "tag": "cse330-hw5",
  "student_id": "1234567890",  // optional, excludes self
  "threshold": 0.4
}
```

#### Batch Compare All Submissions
```bash
POST /api/check_all_pairs
Content-Type: application/json

{
  "tag": "cse330-hw5",
  "threshold": 0.4
}
```

#### Get All Tags
```bash
GET /api/tags
```

#### Get Submissions by Tag
```bash
GET /api/submissions/<tag>
```

#### Delete Submission
```bash
DELETE /api/submission/<submission_id>
```

## Similarity Thresholds

| Score | Verdict |
|-------|---------|
| 80%+ | Almost certainly plagiarized |
| 60-79% | Highly suspicious - likely plagiarism |
| 40-59% | Suspicious similarity |
| 25-39% | Some similarity |
| <25% | Likely independent work |

## Limitations

- Currently only supports C/C++
- Does not detect plagiarism where the algorithm is reimplemented differently
- Does not detect AI-generated code
- Reordering functions or statements will reduce similarity scores

## Tech Stack

- **Backend:** Flask, Tree-sitter, PyMongo
- **Frontend:** Vanilla HTML/CSS/JS
- **Database:** MongoDB
- **Parser:** tree-sitter-cpp

## License

MIT
