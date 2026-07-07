import os
import json
import re
import argparse

def parse_txt_sections(filepath):
    """
    解析一个 txt 文件，按 '## 标题' 行切分成多个小节。
    若某小节没有标题（即文件开头没有 ## 的段落），其 section 为 None。
    返回一个字典列表，每个字典包含 'section' 和 'text'。
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.splitlines()
    sections = []
    current_title = None
    current_lines = []

    # 匹配 "## 任意标题（可能包含空格和标点）"
    title_pattern = re.compile(r'^##\s+(.*?)\s*$')

    for line in lines:
        match = title_pattern.match(line)
        if match:
            # 保存上一个 section
            if current_lines or current_title is not None:
                sections.append({
                    "section": current_title,
                    "text": "\n".join(current_lines).strip()
                })
            current_title = match.group(1).strip()
            current_lines = []
        else:
            # 普通文本行（可能是空行，保留用于自然分段）
            current_lines.append(line)

    # 处理最后一个 section
    if current_lines or current_title is not None:
        sections.append({
            "section": current_title,
            "text": "\n".join(current_lines).strip()
        })

    # 如果整个文件都没有 ##，且内容不为空，则作为一个整体（section 为文件名）
    if not sections and content.strip():
        # 用文件名作为 section 信息
        basename = os.path.splitext(os.path.basename(filepath))[0]
        sections.append({
            "section": basename,
            "text": content.strip()
        })
    # 去掉 text 为空的无效条目（只保留有实质内容的）
    sections = [s for s in sections if s["text"]]
    return sections


def convert_folder(input_dir, output_file):
    """遍历 input_dir 下所有 .txt 文件，解析后写入一个 JSON 数组"""
    all_entries = []
    for filename in sorted(os.listdir(input_dir)):
        if not filename.endswith('.txt'):
            continue
        filepath = os.path.join(input_dir, filename)
        sections = parse_txt_sections(filepath)
        for sec in sections:
            entry = {
                "source_file": filename,
                "section": sec["section"],   # 标题（如”初次见面“”下雨的时候“）
                "text": sec["text"]
            }
            all_entries.append(entry)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_entries, f, ensure_ascii=False, indent=2)

    print(f"✅ 转换完毕！共处理 {len(all_entries)} 个文本片段，保存至 {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="将 Persona 层的 .txt 文件（以 ## 标题分段）转换为结构化的 JSON"
    )
    parser.add_argument("input_dir", help="存放 .txt 文件的目录")
    parser.add_argument("output", help="输出的 JSON 文件路径")
    args = parser.parse_args()

    convert_folder(args.input_dir, args.output)