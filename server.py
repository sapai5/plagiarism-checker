"""
Plagiarism Checker Backend
Flask server that normalizes and compares C++ code using Tree-sitter
With MongoDB storage for batch comparison by tag
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import tree_sitter_cpp as tscpp
from tree_sitter import Language, Parser
from difflib import SequenceMatcher
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime
from dotenv import load_dotenv
import os

app = Flask(__name__)
CORS(app)

load_dotenv(override=True)

# MongoDB setup
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017')
mongo_client = MongoClient(MONGO_URI)
db = mongo_client['plagiarism_checker']
submissions_collection = db['submissions']

submissions_collection.create_index('tag')


class CppNormalizer:
    """Normalizes C++ code by replacing identifiers with canonical names."""

    PRESERVED_NAMES = {
        # Keywords
        'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'default',
        'break', 'continue', 'return', 'goto', 'try', 'catch', 'throw',
        'class', 'struct', 'union', 'enum', 'namespace', 'template',
        'public', 'private', 'protected', 'virtual', 'override', 'final',
        'static', 'const', 'constexpr', 'volatile', 'mutable', 'inline',
        'extern', 'register', 'auto', 'typedef', 'using', 'typename',
        'sizeof', 'alignof', 'decltype', 'nullptr', 'true', 'false',
        'new', 'delete', 'this', 'operator',
        # Built-in types
        'void', 'bool', 'char', 'short', 'int', 'long', 'float', 'double',
        'signed', 'unsigned', 'wchar_t', 'char8_t', 'char16_t', 'char32_t',
        'size_t', 'ptrdiff_t', 'nullptr_t',
        # Common standard library
        'std', 'string', 'vector', 'map', 'set', 'list', 'array',
        'cout', 'cin', 'endl', 'printf', 'scanf', 'malloc', 'free',
        'main', 'argc', 'argv',
    }

    def __init__(self):
        self.parser = Parser(Language(tscpp.language()))

    def normalize_with_mapping(self, code: str) -> tuple:
        """
        Normalize C++ code and return both normalized code and line mapping.
        Returns: (normalized_code, list of original lines corresponding to each normalized line)
        """
        tree = self.parser.parse(bytes(code, 'utf-8'))

        identifier_map = {}
        counter = [0]
        replacements = []

        def get_normalized_name(name: str) -> str:
            if name in self.PRESERVED_NAMES:
                return name
            if name not in identifier_map:
                identifier_map[name] = f'v{counter[0]}'
                counter[0] += 1
            return identifier_map[name]

        def traverse(node):
            if node.type in ('identifier', 'type_identifier', 'field_identifier'):
                name = code[node.start_byte:node.end_byte]
                normalized = get_normalized_name(name)
                if normalized != name:
                    replacements.append((node.start_byte, node.end_byte, normalized))
            # Keep string literals - identical strings are strong evidence of copying
            # Keep number literals - identical magic numbers matter
            # Only strip comments
            elif node.type == 'comment':
                replacements.append((node.start_byte, node.end_byte, ''))

            for child in node.children:
                traverse(child)

        traverse(tree.root_node)

        # Apply replacements in reverse order
        replacements.sort(key=lambda x: x[0], reverse=True)
        result = code
        for start, end, replacement in replacements:
            result = result[:start] + replacement + result[end:]

        # Track mapping: for each normalized line, keep the original line
        original_lines = code.split('\n')
        result_lines = result.split('\n')

        normalized_lines = []
        original_mapping = []  # original line for each normalized line

        for i, line in enumerate(result_lines):
            stripped = ' '.join(line.split())
            if stripped:
                normalized_lines.append(stripped)
                original_mapping.append(original_lines[i] if i < len(original_lines) else '')

        return '\n'.join(normalized_lines), original_mapping

    def normalize(self, code: str) -> str:
        """Normalize C++ code (without mapping)."""
        normalized, _ = self.normalize_with_mapping(code)
        return normalized


# Global normalizer instance
normalizer = CppNormalizer()


def get_diff(norm1: str, norm2: str) -> list:
    """Generate a diff between two normalized code samples."""
    import difflib

    lines1 = norm1.split('\n')
    lines2 = norm2.split('\n')

    differ = difflib.unified_diff(lines1, lines2, lineterm='', fromfile='Sample 1', tofile='Sample 2')
    return list(differ)


def structural_normalize(code: str, parser) -> str:
    """
    Normalize code structurally - ALL identifiers become ID, ALL numbers become NUM.
    This catches plagiarism where only variable names are changed.
    """
    tree = parser.parse(bytes(code, 'utf-8'))

    PRESERVED = {
        'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'default',
        'break', 'continue', 'return', 'goto', 'try', 'catch', 'throw',
        'class', 'struct', 'union', 'enum', 'namespace', 'template',
        'public', 'private', 'protected', 'virtual', 'override', 'final',
        'static', 'const', 'constexpr', 'volatile', 'mutable', 'inline',
        'extern', 'register', 'auto', 'typedef', 'using', 'typename',
        'sizeof', 'alignof', 'decltype', 'nullptr', 'true', 'false',
        'new', 'delete', 'this', 'operator',
        'void', 'bool', 'char', 'short', 'int', 'long', 'float', 'double',
        'signed', 'unsigned', 'size_t', 'string', 'vector', 'map', 'set',
        'cout', 'cin', 'endl', 'printf', 'scanf', 'main', 'std',
        'push_back', 'empty', 'size', 'begin', 'end', 'find', 'insert',
        'sort', 'front', 'back', 'pop_back', 'clear', 'erase',
    }

    replacements = []

    def traverse(node):
        if node.type in ('identifier', 'type_identifier', 'field_identifier'):
            name = code[node.start_byte:node.end_byte]
            if name not in PRESERVED:
                replacements.append((node.start_byte, node.end_byte, 'ID'))
        elif node.type == 'number_literal':
            replacements.append((node.start_byte, node.end_byte, 'NUM'))
        elif node.type == 'string_literal':
            replacements.append((node.start_byte, node.end_byte, 'STR'))
        elif node.type == 'char_literal':
            replacements.append((node.start_byte, node.end_byte, 'CHR'))
        elif node.type == 'comment':
            replacements.append((node.start_byte, node.end_byte, ''))

        for child in node.children:
            traverse(child)

    traverse(tree.root_node)

    replacements.sort(key=lambda x: x[0], reverse=True)
    result = code
    for start, end, replacement in replacements:
        result = result[:start] + replacement + result[end:]

    # Normalize whitespace
    lines = result.split('\n')
    normalized = []
    for line in lines:
        stripped = ' '.join(line.split())
        if stripped:
            normalized.append(stripped)

    return '\n'.join(normalized)


def find_suspicious_patterns(code1: str, code2: str) -> dict:
    """Find suspicious patterns that indicate plagiarism."""
    import re

    # Extract all string literals
    string_pattern = r'"[^"]*"'
    strings1 = set(re.findall(string_pattern, code1))
    strings2 = set(re.findall(string_pattern, code2))

    # Find identical non-trivial strings (longer than simple things like "" or " ")
    common_strings = [s for s in strings1 & strings2 if len(s) > 5]

    # Extract all numeric constants
    num_pattern = r'\b\d+\.\d+\b|\b\d+\b'
    nums1 = set(re.findall(num_pattern, code1))
    nums2 = set(re.findall(num_pattern, code2))

    # Find identical numbers (excluding common ones like 0, 1, 2)
    common_nums = [n for n in nums1 & nums2 if n not in {'0', '1', '2', '10', '100'}]

    # Look for identical multi-line blocks (3+ lines)
    lines1 = [l.strip() for l in code1.split('\n') if l.strip()]
    lines2 = [l.strip() for l in code2.split('\n') if l.strip()]

    identical_blocks = []
    for i in range(len(lines1) - 2):
        block = '\n'.join(lines1[i:i + 3])
        for j in range(len(lines2) - 2):
            if lines1[i:i + 3] == lines2[j:j + 3]:
                if block not in identical_blocks and len(block) > 50:
                    identical_blocks.append(block)

    return {
        'identical_strings': sorted(common_strings, key=len, reverse=True)[:10],
        'identical_numbers': sorted(common_nums)[:20],
        'identical_blocks': identical_blocks[:5],
        'string_count': len(common_strings),
        'block_count': len(identical_blocks)
    }


def get_verdict(score: float) -> dict:
    """Return verdict based on similarity score."""
    if score >= 0.8:
        return {
            'level': 'critical',
            'text': 'Almost certainly plagiarized',
            'description': 'The code samples are nearly identical after normalization. This is very likely copying.'
        }
    elif score >= 0.6:
        return {
            'level': 'high',
            'text': 'Highly suspicious - likely plagiarism',
            'description': 'Strong structural similarity detected. This level of similarity is unlikely to occur by chance.'
        }
    elif score >= 0.4:
        return {
            'level': 'medium',
            'text': 'Suspicious similarity',
            'description': 'Significant similar patterns found. Warrants closer manual inspection.'
        }
    elif score >= 0.25:
        return {
            'level': 'low',
            'text': 'Some similarity',
            'description': 'Some common patterns detected. Could be coincidental or standard idioms.'
        }
    else:
        return {
            'level': 'none',
            'text': 'Likely independent work',
            'description': 'No significant structural similarity detected.'
        }


@app.route('/api/check', methods=['POST'])
def check_plagiarism():
    """Main endpoint to check two code samples for plagiarism."""
    try:
        data = request.get_json()
        code1 = data.get('code1', '')
        code2 = data.get('code2', '')

        if not code1 or not code2:
            return jsonify({'error': 'Both code samples are required'}), 400

        # Structural normalization - ALL identifiers become ID
        # This catches plagiarism where only variable names changed
        struct1 = structural_normalize(code1, normalizer.parser)
        struct2 = structural_normalize(code2, normalizer.parser)

        # Calculate structural similarity (main score)
        struct_matcher = SequenceMatcher(None, struct1, struct2)
        structural_score = struct_matcher.ratio()

        # Also get identifier-aware normalization for the diff view
        norm1 = normalizer.normalize(code1)
        norm2 = normalizer.normalize(code2)

        # Get diff of structural normalization
        diff = get_diff(struct1, struct2)

        # Find suspicious patterns in original code
        suspicious = find_suspicious_patterns(code1, code2)

        # Boost score if many suspicious patterns found
        pattern_boost = min(0.1, suspicious['string_count'] * 0.01 + suspicious['block_count'] * 0.02)
        adjusted_score = min(1.0, structural_score + pattern_boost)

        # Get verdict based on adjusted score
        verdict = get_verdict(adjusted_score)

        return jsonify({
            'score': round(adjusted_score * 100, 1),
            'structural_score': round(structural_score * 100, 1),
            'verdict': verdict,
            'normalized': {
                'code1': struct1,
                'code2': struct2
            },
            'diff': diff,
            'suspicious': suspicious,
            'stats': {
                'original_lines': {
                    'code1': len(code1.split('\n')),
                    'code2': len(code2.split('\n'))
                },
                'normalized_lines': {
                    'code1': len(struct1.split('\n')),
                    'code2': len(struct2.split('\n'))
                }
            }
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/normalize', methods=['POST'])
def normalize_code():
    """Endpoint to just normalize a single code sample."""
    try:
        data = request.get_json()
        code = data.get('code', '')

        if not code:
            return jsonify({'error': 'Code is required'}), 400

        normalized = normalizer.normalize(code)

        return jsonify({
            'original': code,
            'normalized': normalized
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'ok'})


# ============== MongoDB Submission Endpoints ==============

@app.route('/api/submit', methods=['POST'])
def submit_code():
    """Submit code with a tag for storage and comparison."""
    try:
        data = request.get_json()
        code = data.get('code', '')
        tag = data.get('tag', '').strip().lower()
        student_id = data.get('student_id', '').strip()
        filename = data.get('filename', 'submission.cpp')

        if not code or not tag:
            return jsonify({'error': 'Code and tag are required'}), 400

        # Normalize for storage
        struct_normalized = structural_normalize(code, normalizer.parser)

        # Create submission document
        submission = {
            'code': code,
            'normalized': struct_normalized,
            'tag': tag,
            'student_id': student_id,
            'filename': filename,
            'submitted_at': datetime.utcnow()
        }

        result = submissions_collection.insert_one(submission)

        return jsonify({
            'success': True,
            'submission_id': str(result.inserted_id),
            'tag': tag,
            'message': f'Submission stored successfully'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/check_against_tag', methods=['POST'])
def check_against_tag():
    """Check code against all submissions with a specific tag."""
    try:
        data = request.get_json()
        code = data.get('code', '')
        tag = data.get('tag', '').strip().lower()
        threshold = data.get('threshold', 0.4)  # Minimum similarity to report
        student_id = data.get('student_id', '').strip()  # Optional: exclude self

        if not code or not tag:
            return jsonify({'error': 'Code and tag are required'}), 400

        # Normalize the submitted code
        struct_normalized = structural_normalize(code, normalizer.parser)

        # Get all submissions with this tag
        query = {'tag': tag}
        if student_id:
            query['student_id'] = {'$ne': student_id}  # Exclude self

        submissions = list(submissions_collection.find(query))

        if not submissions:
            return jsonify({
                'matches': [],
                'total_compared': 0,
                'message': f'No submissions found for tag: {tag}'
            })

        # Compare against each submission
        matches = []
        for sub in submissions:
            matcher = SequenceMatcher(None, struct_normalized, sub['normalized'])
            score = matcher.ratio()

            if score >= threshold:
                matches.append({
                    'submission_id': str(sub['_id']),
                    'student_id': sub.get('student_id', 'Unknown'),
                    'filename': sub.get('filename', 'Unknown'),
                    'score': round(score * 100, 1),
                    'verdict': get_verdict(score),
                    'submitted_at': sub['submitted_at'].isoformat()
                })

        # Sort by score descending
        matches.sort(key=lambda x: x['score'], reverse=True)

        return jsonify({
            'matches': matches,
            'total_compared': len(submissions),
            'flagged_count': len(matches),
            'tag': tag,
            'threshold': threshold * 100
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/check_all_pairs', methods=['POST'])
def check_all_pairs():
    """Check all submissions with a tag against each other."""
    try:
        data = request.get_json()
        tag = data.get('tag', '').strip().lower()
        threshold = data.get('threshold', 0.4)

        if not tag:
            return jsonify({'error': 'Tag is required'}), 400

        submissions = list(submissions_collection.find({'tag': tag}))

        if len(submissions) < 2:
            return jsonify({
                'pairs': [],
                'total_submissions': len(submissions),
                'message': 'Need at least 2 submissions to compare'
            })

        # Compare all pairs
        flagged_pairs = []
        for i in range(len(submissions)):
            for j in range(i + 1, len(submissions)):
                sub1 = submissions[i]
                sub2 = submissions[j]

                matcher = SequenceMatcher(None, sub1['normalized'], sub2['normalized'])
                score = matcher.ratio()

                if score >= threshold:
                    flagged_pairs.append({
                        'student1': {
                            'id': sub1.get('student_id', 'Unknown'),
                            'filename': sub1.get('filename', 'Unknown'),
                            'submission_id': str(sub1['_id'])
                        },
                        'student2': {
                            'id': sub2.get('student_id', 'Unknown'),
                            'filename': sub2.get('filename', 'Unknown'),
                            'submission_id': str(sub2['_id'])
                        },
                        'score': round(score * 100, 1),
                        'verdict': get_verdict(score)
                    })

        # Sort by score descending
        flagged_pairs.sort(key=lambda x: x['score'], reverse=True)

        return jsonify({
            'pairs': flagged_pairs,
            'total_submissions': len(submissions),
            'total_pairs_checked': len(submissions) * (len(submissions) - 1) // 2,
            'flagged_count': len(flagged_pairs),
            'tag': tag,
            'threshold': threshold * 100
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tags', methods=['GET'])
def get_tags():
    """Get all unique tags with submission counts."""
    try:
        pipeline = [
            {'$group': {'_id': '$tag', 'count': {'$sum': 1}}},
            {'$sort': {'_id': 1}}
        ]
        tags = list(submissions_collection.aggregate(pipeline))

        return jsonify({
            'tags': [{'tag': t['_id'], 'count': t['count']} for t in tags]
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/submissions/<tag>', methods=['GET'])
def get_submissions_by_tag(tag):
    """Get all submissions for a specific tag."""
    try:
        tag = tag.strip().lower()
        submissions = list(submissions_collection.find(
            {'tag': tag},
            {'code': 0, 'normalized': 0}  # Exclude large fields
        ).sort('submitted_at', -1))

        return jsonify({
            'submissions': [{
                'id': str(s['_id']),
                'student_id': s.get('student_id', 'Unknown'),
                'filename': s.get('filename', 'Unknown'),
                'submitted_at': s['submitted_at'].isoformat()
            } for s in submissions],
            'tag': tag,
            'count': len(submissions)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/submission/<submission_id>', methods=['GET'])
def get_submission(submission_id):
    """Get a specific submission by ID."""
    try:
        submission = submissions_collection.find_one({'_id': ObjectId(submission_id)})

        if not submission:
            return jsonify({'error': 'Submission not found'}), 404

        return jsonify({
            'id': str(submission['_id']),
            'code': submission['code'],
            'normalized': submission['normalized'],
            'tag': submission['tag'],
            'student_id': submission.get('student_id', 'Unknown'),
            'filename': submission.get('filename', 'Unknown'),
            'submitted_at': submission['submitted_at'].isoformat()
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/submission/<submission_id>', methods=['DELETE'])
def delete_submission(submission_id):
    """Delete a specific submission."""
    try:
        result = submissions_collection.delete_one({'_id': ObjectId(submission_id)})

        if result.deleted_count == 0:
            return jsonify({'error': 'Submission not found'}), 404

        return jsonify({'success': True, 'message': 'Submission deleted'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("Starting Plagiarism Checker API on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)