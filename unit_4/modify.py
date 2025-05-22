import json
from typing import *
import os
import javalang
import time
import random
import base64
import argparse

def parse_args():
    parser = argparse.ArgumentParser(description="UML和Java类同步处理脚本")
    parser.add_argument('--src', type=str, required=True, help='Java源代码目录')
    parser.add_argument('--uml', type=str, required=True, help='uml.json文件路径')
    return parser.parse_args()

class IdGenerator:
    _counter = 0

    def __init__(self):
        self.base_hex = ''
    
    def set_base_hex(self, val):
        self.base_hex = val

    def to_hex(self, digit, num):
        hex_str = hex(num)[2:]
        return hex_str.zfill(digit)

    def hex_to_bytes(self, hex_str):
        return bytes.fromhex(hex_str)

    def hex_to_base64(self, hex_str):
        b = self.hex_to_bytes(hex_str)
        return base64.b64encode(b).decode('ascii')

    def generate(self):
        timestamp = int(time.time() * 1000)
        timestamp_hex = self.to_hex(16, timestamp)
        counter = IdGenerator._counter
        IdGenerator._counter = (IdGenerator._counter + 1) % 65536
        counter_hex = self.to_hex(4, counter)
        rand_num = random.randint(0, 65535)
        rand_hex = self.to_hex(4, rand_num)
        full_hex = self.base_hex + timestamp_hex + counter_hex + rand_hex
        base64_id = self.hex_to_base64(full_hex)
        return base64_id

gen = IdGenerator()
gen.set_base_hex('0000')

all_classes = []
uml_classes = {}

def get_all_java_files(folder_path):
    java_files = []
    for root, _, files in os.walk(folder_path):
        for file in files:
            if file.endswith('.java'):
                java_files.append(os.path.join(root, file))
    return java_files

def get_defined_classes(java_file):
    class_names = []
    with open(java_file, 'r', encoding='utf-8') as file:
        code = file.read()
    try:
        tree = javalang.parse.parse(code)
        for _, node in tree.filter(javalang.tree.ClassDeclaration):
            if node.body:
                class_names.append(node.name)
    except Exception as e:
        print(f"解析 {java_file} 时出错：{e}")
    return class_names

def findUMLClasses(data) -> Dict :
    res = {}
    if isinstance(data, dict):
        if data.get('_type') == 'UMLClass':
            res[data.get('_id')] = data.get('name')
        for value in data.values():
            res.update(findUMLClasses(value))
    elif isinstance(data, list):
        for item in data:
            res.update(findUMLClasses(item))
    return res

def findRef(data):
    if isinstance(data, dict):
        if data.get('type') is not None:
            t = data.get('type')
            if isinstance(t, dict) and t.get('$ref') is not None:
                name = uml_classes.get(t.get('$ref'))
                if name not in all_classes:
                    data['type'] = name
        for value in data.values():
            findRef(value)
    elif isinstance(data, list):
        for item in data:
            findRef(item)

def delClass(obj):
    def check_id(id_value):
        return uml_classes[id_value] not in all_classes
    if isinstance(obj, dict):
        keys_to_delete = []
        for key, value in obj.items():
            if (isinstance(value, dict) and
                value.get("_type") == "UMLClass" and
                "_id" in value and
                check_id(value["_id"])):
                keys_to_delete.append(key)
            else:
                delClass(value)
        for key in keys_to_delete:
            del obj[key]
    elif isinstance(obj, list):
        for i in range(len(obj)-1, -1, -1):
            item = obj[i]
            if (isinstance(item, dict) and
                item.get("_type") == "UMLClass" and
                "_id" in item and
                check_id(item["_id"])):
                obj.pop(i)
            else:
                delClass(item)

def modifyCollection(data):
    if isinstance(data, dict):
        if data.get('type') is not None and data.get('multiplicity') == '*':
            data.pop('multiplicity')
            subtype = data.get('type')
            if data.get('tags') is not None:
                supertype = data.get('tags')[0]['value']
                data['type'] = f"{supertype}<{subtype}>"
                data.pop('tags')
            else:
                data['type'] = f"{subtype}[]"
        for value in data.values():
            modifyCollection(value)
    elif isinstance(data, list):
        for item in data:
            modifyCollection(item)

def modifyAssociation(data):
    if isinstance(data, dict):
        if data.get("ownedElements") is not None:
            appendAttributes = []
            for item in data.get("ownedElements"):
                if item.get('_type') == "UMLAssociation" and item.get('end2').get('name') is not None:
                    name = item.get('end2').pop('name')
                    subtype = item.get('end2').get('reference')
                    visibility = item.get('end2').pop('visibility')
                    is_read_only = False
                    if item.get('end2').get('isReadOnly') is not None:
                        is_read_only = item.get('end2').pop('isReadOnly')
                    item.get('end2').pop('navigable')
                    item.get('end1').pop('visibility')
                    if item.get('end2').get('multiplicity') == '*':
                        subtype = uml_classes[item.get('end2').get('reference').get('$ref')]
                        if item.get('end2').get('tags') is not None:
                            supertype = item.get('end2').get('tags')[0].get('value')
                            t = f"{supertype}<{subtype}>"
                            item.get('end2').pop('tags')
                        else:
                            t = f"{subtype}[]"
                        item.get('end2').pop('multiplicity')
                    else:
                        t = subtype
                    attr = {
                        "_type": "UMLAttribute",
                        "_id": gen.generate(),
                        "_parent": {
                            "$ref": data["_id"]
                        },
                        "name": name,
                        "visibility": visibility,
                        "type": t
                    }
                    if is_read_only:
                        attr["isLeaf"] = True
                        attr["isReadOnly"] = True
                    
                    appendAttributes.append(attr)
            if data.get('attributes') is not None:
                data['attributes'].extend(appendAttributes)
            else:
                data['attributes'] = appendAttributes
        for value in data.values():
            modifyAssociation(value)
    elif isinstance(data, list):
        for item in data:
            modifyAssociation(item)

def modifyModel(model: Dict):
    global uml_classes
    model["name"] = "Model"
    uml_classes = findUMLClasses(model)
    findRef(model)
    delClass(model)
    modifyCollection(model)
    modifyAssociation(model)

def main(src_dir, uml_json_path):
    global all_classes
    all_classes = []
    java_files = get_all_java_files(src_dir)
    for java_file in java_files:
        classes = get_defined_classes(java_file)
        all_classes.extend(classes)
    with open(uml_json_path, "r", encoding='utf-8') as f:
        prj = json.load(f)
    prj["name"] = "UMLGraph"
    java_reverse = prj["ownedElements"].pop()
    old_model = prj["ownedElements"].pop()
    old_model["ownedElements"][0]['name'] = "MainGraph"
    old_model["ownedElements"][0]["_parent"]["$ref"] = java_reverse["_id"]
    java_reverse["ownedElements"].extend(old_model["ownedElements"])
    modifyModel(java_reverse)
    prj["ownedElements"].append(java_reverse)
    with open(uml_json_path, "w", encoding='utf-8') as f:
        json.dump(prj, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    args = parse_args()
    main(args.src, args.uml)