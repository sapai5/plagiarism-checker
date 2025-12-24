"""
Plagiarism Checker Backend
Flask server that normalizes and compares C++ code using Tree-sitter
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import tree_sitter_cpp as tscpp
from tree_sitter import Language, Parser
from difflib import SequenceMatcher

app = Flask(__name__)
CORS(app)


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


if __name__ == '__main__':
    print("Starting Plagiarism Checker API on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)