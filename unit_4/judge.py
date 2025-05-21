import json
import os
import argparse
import javalang
from collections import defaultdict
import re

# --- 全局变量和辅助函数 ---
PASS_MSG = "通过"
FAIL_MSG = "失败"
INFO_MSG = "信息"
WARN_MSG = "警告" # New message type

# UML JSON中的可见性映射
UML_VISIBILITY_MAP = {
    "public": "public", "private": "private", "protected": "protected",
    "package": "package", None: "public"
}
JAVA_MODIFIER_VISIBILITY_MAP = {
    "public": "public", "private": "private", "protected": "protected"
}
PRIMITIVE_EQUIVALENCE_MAP = {
    "boolean": ["boolean", "Boolean"], "byte": ["byte", "Byte"],
    "short": ["short", "Short"], "int": ["int", "Integer"],
    "long": ["long", "Long"], "float": ["float", "Float"],
    "double": ["double", "Double"], "char": ["char", "Character"]
}

def resolve_uml_type(type_value, id_to_name_map):
    if type_value is None: return "void" # If a return param exists but its type is null
    if isinstance(type_value, str): return type_value
    if isinstance(type_value, dict) and "$ref" in type_value:
        ref_id = type_value["$ref"]
        return id_to_name_map.get(ref_id, f"unresolved_ref({ref_id})")
    return "unknown_type_format"

class UMLElement:
    def __init__(self, name, visibility, el_type):
        self.name, self.visibility, self.el_type = name, visibility, el_type

class UMLAttribute(UMLElement):
    def __init__(self, name, visibility, raw_attr_type, id_to_name_map, is_static=False, multiplicity=None):
        super().__init__(name, visibility, 'attribute')
        self.raw_attr_type = raw_attr_type
        self.attr_type = resolve_uml_type(raw_attr_type, id_to_name_map)
        self.is_static = is_static
        self.multiplicity = multiplicity if multiplicity else "1"
    def __repr__(self): return f"UMLAttr({self.name}, {self.visibility}, {self.attr_type}, static={self.is_static}, mult={self.multiplicity})"

class UMLOperation(UMLElement):
    def __init__(self, name, visibility, raw_return_type_info, id_to_name_map, is_static=False, class_name_context=""):
        super().__init__(name, visibility, 'operation')
        self.parameters = [] # To be filled by add_parameter
        self.raw_return_type_info = raw_return_type_info # Store the raw info for reference
        self.is_static = is_static
        self.class_name_context = class_name_context
        
        # Determine default return type before trying to resolve from raw_return_type_info
        if self.name == self.class_name_context: # Is it a constructor?
            self.return_type = "void" # Default for constructors (for comparison with Java's implicit void)
        else:
            self.return_type = "void" # Default for regular methods if no return parameter or type is specified

        # Now, try to override with actual UML return type if present
        if raw_return_type_info and 'type' in raw_return_type_info:
             resolved_type = resolve_uml_type(raw_return_type_info['type'], id_to_name_map)
             # Even for constructors, if UML *explicitly* states a return type (e.g., the class name), use it.
             # The comparison logic in main() will handle constructor "ClassName" (UML) vs "void" (Java).
             self.return_type = resolved_type
        elif raw_return_type_info and 'type' not in raw_return_type_info and self.name != self.class_name_context:
            # A return parameter exists, but it has no 'type' field.
            # For a non-constructor, this usually means the type is implicitly void in UML tools,
            # or it's an error in the UML model itself if the tool expects a type.
            # resolve_uml_type(None, ...) would return "void", so self.return_type remains "void".
            # The check for the *existence* of raw_return_type_info is now in parse_uml_model.
            pass


    def add_parameter(self, name, raw_param_type, id_to_name_map):
        self.parameters.append({'name': name, 'type': resolve_uml_type(raw_param_type, id_to_name_map), 'raw_type': raw_param_type})
    def __repr__(self): return f"UMLOp({self.name}({', '.join(f'{p["name"]}:{p["type"]}' for p in self.parameters)}):{self.return_type}, {self.visibility}, static={self.is_static})"

class UMLClass:
    def __init__(self, name):
        self.name = name
        self.attributes, self.operations, self.associations_to, self.dependencies_to = \
            {}, defaultdict(list), [], []
    def __repr__(self): return f"UMLClass({self.name}, Attrs:{len(self.attributes)}, Ops:{sum(len(v) for v in self.operations.values())})"

class JavaElement:
    def __init__(self, name, visibility, el_type):
        self.name, self.visibility, self.el_type = name, visibility, el_type

class JavaField(JavaElement):
    def __init__(self, name, visibility, field_type, is_static=False, is_final=False):
        super().__init__(name, visibility, 'field')
        self.field_type, self.is_static, self.is_final = field_type, is_static, is_final
    def __repr__(self): return f"JavaField({self.name}, {self.visibility}, {self.field_type}, static={self.is_static}, final={self.is_final})"

class JavaMethod(JavaElement):
    def __init__(self, name, visibility, return_type="void", is_static=False, is_constructor=False):
        super().__init__(name, visibility, 'method')
        self.parameters, self.return_type, self.is_static, self.is_constructor = \
            [], return_type if return_type is not None else "void", is_static, is_constructor
    def add_parameter(self, name, param_type_str): self.parameters.append({'name': name, 'type': param_type_str})
    def __repr__(self): return f"JavaMethod({self.name}({', '.join(f'{p["name"]}:{p["type"]}' for p in self.parameters)}):{self.return_type}, {self.visibility}, static={self.is_static})"

class JavaClass:
    def __init__(self, name, filepath=None):
        self.name, self.filepath = name, filepath
        self.fields, self.methods, self.imports = {}, defaultdict(list), set()
    def __repr__(self): return f"JavaClass({self.name}, Fields:{len(self.fields)}, Methods:{sum(len(v) for v in self.methods.values())})"

def parse_uml_model(mdj_path):
    uml_classes = {}
    uml_root = None
    model_element = None
    with open(mdj_path, 'r', encoding='utf-8') as f: uml_json = json.load(f)
    if uml_json.get("_type") == "Project":
        uml_root = uml_json
        for elem in uml_json.get("ownedElements", []):
            if elem.get("_type") == "UMLModel" and elem.get("name") == "Model":
                model_element = elem; break
        else: print(f"{FAIL_MSG}: R0 - 未找到名为 'Model' 的 UMLModel."); return None, {}, {}
    else: print(f"{FAIL_MSG}: R0 - 顶层元素不是 'Project' 类型."); return None, {}, {}
    print(f"{PASS_MSG}: R0 - UMLModel 名称为 'Model'。")
    id_to_name_map = {}
    raw_class_elements = []
    if model_element:
        for item_data in model_element.get("ownedElements", []):
            item_type = item_data.get("_type")
            if item_type == "UMLClass" or item_type == "UMLInterface":
                item_id = item_data.get("_id"); item_name = item_data.get("name")
                if item_id and item_name: id_to_name_map[item_id] = item_name
                if item_type == "UMLClass": raw_class_elements.append(item_data)
    else: print(f"{FAIL_MSG}: R0 - UMLModel 'Model' 内部为空或无法访问."); return None, {}, {}
    for item_data in raw_class_elements:
        class_name = item_data.get("name")
        if not class_name: print(f"{FAIL_MSG}: R1 - 发现一个没有名称的UMLClass (ID: {item_data.get('_id')})。"); continue
        if class_name in uml_classes: print(f"{FAIL_MSG}: R1 - UML中存在重名类: {class_name}。"); continue
        uml_c = UMLClass(class_name)
        for attr_data in item_data.get("attributes", []):
            attr_name = attr_data.get("name")
            if not attr_name: print(f"{FAIL_MSG}: R1 - 类 {class_name} 中发现一个没有名称的UMLAttribute。"); continue
            visibility = UML_VISIBILITY_MAP.get(attr_data.get("visibility"))
            raw_attr_type = attr_data.get("type"); is_static_attr = attr_data.get("isStatic", False)
            attr_multiplicity = attr_data.get("multiplicity") 
            uml_c.attributes[attr_name] = UMLAttribute(attr_name, visibility, raw_attr_type, id_to_name_map, is_static_attr, attr_multiplicity)
        for op_data in item_data.get("operations", []):
            current_op_name = op_data.get("name")
            if not current_op_name: print(f"{FAIL_MSG}: R1 - 类 {class_name} 中发现一个没有名称的UMLOperation。"); continue
            visibility = UML_VISIBILITY_MAP.get(op_data.get("visibility")); is_static_op = op_data.get("isStatic", False)
            
            raw_return_type_info = None # This will store the UMLParameter object for the return type
            op_params_data_for_op = []
            
            for param_data in op_data.get("parameters", []):
                if param_data.get("direction") == "return": 
                    raw_return_type_info = param_data
                else: 
                    op_params_data_for_op.append(param_data)
            
            # --- NEW CHECK ---
            # Check if this operation is a constructor
            is_constructor_op = (current_op_name == class_name)
            if not is_constructor_op: # If it's a regular (non-constructor) method
                if raw_return_type_info is None:
                    # This means no parameter with direction="return" was found in the UML model for this operation.
                    print(f"{FAIL_MSG}: UML规范检查 - 类 {class_name} 的常规方法 '{current_op_name}' 在UML中未明确定义返回类型参数 (根据指导书要求，除构造方法外，每个方法必须有一个返回参数)。")
                # If raw_return_type_info exists, but its 'type' field is missing,
                # UMLOperation constructor will default its return_type to "void" (or "unknown_type_format"),
                # and R2 checks will catch mismatches with Java. The primary new check is for the *absence* of the return parameter.
            # --- END OF NEW CHECK ---

            uml_op = UMLOperation(current_op_name, visibility, raw_return_type_info, id_to_name_map, is_static_op, class_name_context=class_name)
            
            for param_data in op_params_data_for_op: # These are non-return parameters
                param_name = param_data.get("name")
                if not param_name: print(f"{FAIL_MSG}: R1 - 类 {class_name} 方法 {current_op_name} 中发现一个没有名称的UMLParameter (非返回类型)。"); continue
                raw_param_type = param_data.get("type")
                uml_op.add_parameter(param_name, raw_param_type, id_to_name_map)
            uml_c.operations[current_op_name].append(uml_op)
        for owned_elem in item_data.get("ownedElements", []):
            if owned_elem.get("_type") == "UMLAssociation":
                end1 = owned_elem.get("end1"); end2 = owned_elem.get("end2")
                if end1 and end2 and end1.get("reference", {}).get("$ref") == item_data.get("_id"):
                    target_ref_id = end2.get("reference", {}).get("$ref")
                    target_class_name = id_to_name_map.get(target_ref_id)
                    navigable_val = end2.get("navigable"); is_navigable = navigable_val is True or navigable_val == "navigable"
                    if target_class_name and is_navigable:
                        uml_c.associations_to.append({
                            "target_class_name": target_class_name, "role_name": end2.get("name"),
                            "multiplicity": end2.get("multiplicity")})
            elif owned_elem.get("_type") == "UMLDependency":
                source_ref_id = owned_elem.get("source", {}).get("$ref"); target_ref_id = owned_elem.get("target", {}).get("$ref")
                if source_ref_id == item_data.get("_id"):
                    target_class_name = id_to_name_map.get(target_ref_id)
                    if target_class_name: uml_c.dependencies_to.append(target_class_name)
        uml_classes[class_name] = uml_c
    return uml_root, uml_classes, id_to_name_map

def get_java_type_str(type_node):
    if type_node is None: return "void"
    if isinstance(type_node, str): return type_node
    base_type = "unknown_base_type"
    if hasattr(type_node, 'name') and type_node.name is not None: base_type = type_node.name
    arguments_str = ""
    if hasattr(type_node, 'arguments') and type_node.arguments:
        args = []
        for arg_type_obj in type_node.arguments:
            current_arg_type_str = "unknown_arg"
            if hasattr(arg_type_obj, 'type') and arg_type_obj.type: current_arg_type_str = get_java_type_str(arg_type_obj.type)
            elif hasattr(arg_type_obj, 'pattern') and arg_type_obj.pattern and hasattr(arg_type_obj.pattern, 'sub_type'):
                bound_kw = "?"
                if hasattr(arg_type_obj, 'provision') and arg_type_obj.provision: bound_kw += f" {arg_type_obj.provision} {get_java_type_str(arg_type_obj.pattern.type)}" if arg_type_obj.pattern.type else f" {arg_type_obj.provision} {arg_type_obj.pattern.sub_type}"
                current_arg_type_str = bound_kw
            else: current_arg_type_str = "?"
            args.append(current_arg_type_str)
        if args: arguments_str = f"<{', '.join(args)}>"
    dimensions_str = ""
    if hasattr(type_node, 'dimensions') and type_node.dimensions is not None:
        processed_dimensions = []
        for d_item in type_node.dimensions:
            if d_item is None: processed_dimensions.append("[]")
            elif isinstance(d_item, str): processed_dimensions.append(d_item)
        dimensions_str = "".join(processed_dimensions)
    if base_type == "unknown_base_type" and dimensions_str: return f"unknown_array_base{dimensions_str}"
    return base_type + arguments_str + dimensions_str

def normalize_uml_type(type_str):
    if not isinstance(type_str, str): return "unknown_input_to_normalize_uml" 
    if type_str.startswith("unresolved_ref("): return type_str 
    temp_type = type_str; is_array = False
    if temp_type.endswith("[]"): is_array = True; temp_type = temp_type[:-2]
    if "<" in temp_type and ">" in temp_type: temp_type = temp_type.split("<")[0]
    return temp_type + ("[]" if is_array else "")

def normalize_java_type_str(type_str):
    if not isinstance(type_str, str): return "unknown_input_to_normalize_java"
    common_mappings = {"java.lang.String": "String", "String": "String", "java.time.LocalDate": "LocalDate", "LocalDate": "LocalDate", "java.util.List": "List", "List": "List", "java.util.LinkedList": "LinkedList", "LinkedList": "LinkedList", "java.util.HashMap" : "HashMap", "HashMap": "HashMap", "java.util.ArrayList": "ArrayList", "ArrayList": "ArrayList", "java.util.Map": "Map", "Map": "Map", "java.util.Set": "Set", "Set": "Set", "boolean": "boolean", "Boolean": "Boolean", "int": "int", "Integer": "Integer", "char": "char", "Character": "Character", "double": "double", "Double": "Double", "long": "long", "Long": "Long", "float": "float", "Float": "Float", "short": "short", "Short": "Short", "byte": "byte", "Byte": "Byte", "void": "void"}
    if type_str in common_mappings: return common_mappings[type_str]
    temp_type = type_str; is_array = False
    if temp_type.endswith("[]"): is_array = True; temp_type = temp_type[:-2]
    if "<" in temp_type and ">" in temp_type: temp_type = temp_type.split("<")[0]
    if temp_type in common_mappings: return common_mappings[temp_type] + ("[]" if is_array else "")
    if '.' in temp_type: return temp_type.split('.')[-1] + ("[]" if is_array else "")
    return type_str

def get_canonical_primitive_base(type_name_variant):
    is_array = type_name_variant.endswith("[]")
    base_name = type_name_variant[:-2] if is_array else type_name_variant
    for canonical, variants in PRIMITIVE_EQUIVALENCE_MAP.items():
        if base_name in variants: return canonical, is_array
    return base_name, is_array

def are_types_equivalent(uml_type_str, java_type_str):
    if not isinstance(uml_type_str, str) or not isinstance(java_type_str, str): return False
    norm_uml_type = normalize_uml_type(uml_type_str)
    norm_java_type = normalize_java_type_str(java_type_str)
    if norm_uml_type == norm_java_type: return True
    if norm_uml_type.startswith("unresolved_ref("): return norm_java_type in ["unknown_base_type", "unknown_type_format", "unknown_array_base", "unknown_input_to_normalize_java"]
    uml_base_canon, uml_is_array = get_canonical_primitive_base(norm_uml_type)
    java_base_canon, java_is_array = get_canonical_primitive_base(norm_java_type)
    if uml_is_array != java_is_array: return False
    return uml_base_canon == java_base_canon

def parse_java_directory(src_dir):
    java_classes = {}
    for root, _, files in os.walk(src_dir):
        for file_name_in_dir in files: 
            if file_name_in_dir.endswith(".java"):
                filepath = os.path.join(root, file_name_in_dir)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f_content: content = f_content.read() 
                    tree = javalang.parse.parse(content)
                    current_imports = set()
                    if tree.imports:
                        for imp in tree.imports:
                            if imp.path is not None: current_imports.add(imp.path)
                    if tree.types is None: continue
                    for type_declaration in tree.types:
                        if isinstance(type_declaration, javalang.tree.ClassDeclaration):
                            node = type_declaration; class_name = node.name
                            if class_name is None: print(f"{INFO_MSG}: Found class with no name in {filepath}, skipping."); continue
                            java_c = JavaClass(class_name, filepath=filepath) 
                            java_c.imports = current_imports
                            if node.body is None: java_classes[class_name] = java_c; continue
                            for member in node.body:
                                if member is None: continue
                                if isinstance(member, javalang.tree.FieldDeclaration):
                                    visibility = "package"; is_static_field = False; is_final_field = False
                                    if member.modifiers:
                                        for mod in member.modifiers:
                                            if mod in JAVA_MODIFIER_VISIBILITY_MAP: visibility = JAVA_MODIFIER_VISIBILITY_MAP[mod]
                                            if mod == 'static': is_static_field = True
                                            if mod == 'final': is_final_field = True
                                    field_type_str = get_java_type_str(member.type)
                                    if member.declarators:
                                        for decl in member.declarators:
                                            if decl.name is None: continue
                                            java_c.fields[decl.name] = JavaField(decl.name, visibility, field_type_str, is_static_field, is_final_field)
                                elif isinstance(member, (javalang.tree.MethodDeclaration, javalang.tree.ConstructorDeclaration)):
                                    method_name_attr = getattr(member, 'name', None)
                                    is_constructor = isinstance(member, javalang.tree.ConstructorDeclaration)
                                    method_name_to_store = class_name if is_constructor else method_name_attr
                                    if method_name_to_store is None : print(f"{INFO_MSG}: Found method/constructor with no name in {class_name if class_name else 'UnnamedClass'} in {filepath}, skipping."); continue
                                    visibility = "package"; is_static_method = False
                                    if member.modifiers:
                                        for mod in member.modifiers:
                                            if mod in JAVA_MODIFIER_VISIBILITY_MAP: visibility = JAVA_MODIFIER_VISIBILITY_MAP[mod]
                                            if mod == 'static': is_static_method = True
                                    return_type_node = getattr(member, 'return_type', None)
                                    return_type_str = get_java_type_str(return_type_node)
                                    java_m = JavaMethod(method_name_to_store, visibility, return_type_str, is_static_method, is_constructor)
                                    if member.parameters is not None:
                                        for param in member.parameters:
                                            if param.name is None: continue
                                            param_type_node = getattr(param, 'type', None)
                                            if param_type_node is None: print(f"{INFO_MSG}: Parameter '{param.name}' in method '{method_name_to_store}' of class '{class_name}' has no type information, skipping parameter."); continue
                                            param_type_str = get_java_type_str(param_type_node)
                                            java_m.add_parameter(param.name, param_type_str)
                                    java_c.methods[method_name_to_store].append(java_m)
                            java_classes[class_name] = java_c
                except javalang.parser.JavaSyntaxError as e: print(f"语法错误导致解析Java文件 {filepath} 失败: {e}")
                except Exception as e: print(f"解析Java文件 {filepath} 失败 ({type(e).__name__}): {e}")
    return java_classes


def compare_parameters(uml_op_params, java_method_params, class_name_context):
    if len(uml_op_params) != len(java_method_params): return False, f"参数数量不匹配 (UML: {len(uml_op_params)}, Java: {len(java_method_params)})"
    for i, uml_p_info in enumerate(uml_op_params):
        java_p_info = java_method_params[i]; uml_param_name = uml_p_info['name']; java_param_name = java_p_info['name']
        uml_param_type_str = uml_p_info['type']; java_param_type_str = java_p_info['type']
        if uml_param_name != java_param_name: return False, f"参数名称不匹配 (UML: {uml_param_name}, Java: {java_param_name})"
        if not are_types_equivalent(uml_param_type_str, java_param_type_str):
            if uml_param_type_str.startswith("unresolved_ref("): print(f"{INFO_MSG}: 参数 '{uml_param_name}' (类 {class_name_context}) 的 UML 类型 '{uml_param_type_str}' 未能解析。Java类型: '{java_param_type_str}'.")
            norm_uml = normalize_uml_type(uml_param_type_str); norm_java = normalize_java_type_str(java_param_type_str)
            return False, f"参数 '{uml_param_name}' 类型不匹配 (UML: {uml_param_type_str} (norm: {norm_uml}), Java: {java_param_type_str} (norm: {norm_java}))"
    return True, ""

# --- R5 HELPER FUNCTIONS ---
def get_element_type_and_is_collection(type_str):
    if not isinstance(type_str, str): return (str(type_str), False)
    array_match = re.fullmatch(r"(.+?)(\[\]+)", type_str) 
    if array_match:
        return (normalize_java_type_str(array_match.group(1)), True) 
    generic_match = re.fullmatch(r"(?:List|Set|Collection|Iterable)<(.+)>", type_str)
    if generic_match:
        inner_type_str = generic_match.group(1).strip()
        return (normalize_java_type_str(inner_type_str), True) 
    map_match = re.fullmatch(r"(?:Map|HashMap|LinkedHashMap|TreeMap)<.*,\s*(.+)>", type_str)
    if map_match:
        value_type_str = map_match.group(1).strip()
        return (normalize_java_type_str(value_type_str), True) 
    return (normalize_java_type_str(type_str), False)


def is_multiplicity_many(multiplicity_string):
    if not multiplicity_string: return False
    if isinstance(multiplicity_string, (int, float)): return multiplicity_string > 1
    multiplicity_string = str(multiplicity_string).strip()
    if "*" in multiplicity_string or "n" in multiplicity_string.lower(): return True
    if ".." in multiplicity_string:
        try:
            lower, upper = map(str.strip, multiplicity_string.split(".."))
            if not upper.isdigit() and upper != '*': return True
            if upper == '*': return True
            if upper.isdigit() and int(upper) == 1: return False
            if upper.isdigit() and int(upper) > 1: return True
            if lower.isdigit() and int(lower) > 1: return True
        except ValueError: pass
    if multiplicity_string.isdigit(): return int(multiplicity_string) > 1
    return False


def main():
    parser = argparse.ArgumentParser(description="对照UML类图和Java源代码进行检查。")
    parser.add_argument("src_dir", help="Java源代码目录 (例如 src)")
    parser.add_argument("uml_file", help="UML模型文件 (uml.mdj)")
    args = parser.parse_args()
    print(f"开始解析UML文件: {args.uml_file}")
    uml_root_data, uml_data, id_to_name_map_global = parse_uml_model(args.uml_file)
    if not uml_root_data: return
    print(f"\n开始解析Java目录: {args.src_dir}")
    java_data = parse_java_directory(args.src_dir)
    print("\n--- R2/R5: 类图与程序一致性检验 ---")
    uml_class_names = set(uml_data.keys()); java_class_names = set(java_data.keys())
    missing_in_java = uml_class_names - java_class_names
    for mc_name in sorted(list(missing_in_java)): print(f"{FAIL_MSG}: UML类 '{mc_name}' 在Java源代码中未找到。")
    missing_in_uml = java_class_names - uml_class_names
    for jc_name in sorted(list(missing_in_uml)): print(f"{FAIL_MSG}: Java类 '{jc_name}' 在UML模型中未找到。")
    common_classes = uml_class_names.intersection(java_class_names)
    print(f"\n共有的类 ({len(common_classes)}): {', '.join(sorted(list(common_classes))) if common_classes else '无'}")

    for class_name in sorted(list(common_classes)):
        print(f"\n--- 正在检查类: {class_name} ---")
        uml_c = uml_data[class_name]; java_c = java_data[class_name]
        
        if java_c.fields:
            attr_perc = (len(uml_c.attributes) / len(java_c.fields)) * 100 if len(java_c.fields) > 0 else (100.0 if not uml_c.attributes else 0.0)
            if len(uml_c.attributes) < 0.6 * len(java_c.fields): print(f"{FAIL_MSG}: 类 {class_name}: UML属性数量 ({len(uml_c.attributes)}) 不足Java字段数量 ({len(java_c.fields)}) 的60%。 ({attr_perc:.2f}%)")
            else: print(f"{PASS_MSG}: 类 {class_name}: UML属性数量/Java字段数量 = {attr_perc:.2f}% (>=60%)")
        elif uml_c.attributes: print(f"{INFO_MSG}: 类 {class_name}: Java中无字段，UML有 {len(uml_c.attributes)} 属性 (60%规则通过，视为UML满足要求)")
        else: print(f"{PASS_MSG}: 类 {class_name}: UML和Java均无属性/字段 (60%规则通过)")

        java_method_count = sum(len(v) for v in java_c.methods.values())
        uml_op_count = sum(len(v) for v in uml_c.operations.values())
        if java_method_count > 0:
            op_perc = (uml_op_count / java_method_count) * 100
            if uml_op_count < 0.6 * java_method_count: print(f"{FAIL_MSG}: 类 {class_name}: UML操作数量 ({uml_op_count}) 不足Java方法数量 ({java_method_count}) 的60%。 ({op_perc:.2f}%)")
            else: print(f"{PASS_MSG}: 类 {class_name}: UML操作数量/Java方法数量 = {op_perc:.2f}% (>=60%)")
        elif uml_op_count > 0: print(f"{INFO_MSG}: 类 {class_name}: Java中无方法，UML有 {uml_op_count} 操作 (60%规则通过，视为UML满足要求)")
        else: print(f"{PASS_MSG}: 类 {class_name}: UML和Java均无操作/方法 (60%规则通过)")

        for attr_name, uml_attr in uml_c.attributes.items():
            if attr_name not in java_c.fields: print(f"{FAIL_MSG}: 类 {class_name}: UML属性 '{attr_name}' 在Java中未找到。"); continue
            java_field = java_c.fields[attr_name]
            if uml_attr.visibility != java_field.visibility: print(f"{FAIL_MSG}: 类 {class_name} 属性 '{attr_name}': 可见性不匹配 (UML: {uml_attr.visibility}, Java: {java_field.visibility})。")
            if not are_types_equivalent(uml_attr.attr_type, java_field.field_type):
                if uml_attr.attr_type.startswith("unresolved_ref("): print(f"{INFO_MSG}: 类 {class_name} 属性 '{attr_name}': UML类型为未解析引用 '{uml_attr.attr_type}', Java类型为 '{java_field.field_type}'. 此处视为类型不匹配。")
                print(f"{FAIL_MSG}: 类 {class_name} 属性 '{attr_name}': 类型不匹配 (UML: {uml_attr.attr_type}, Java: {java_field.field_type})。(Normalized: UML '{normalize_uml_type(uml_attr.attr_type)}', Java '{normalize_java_type_str(java_field.field_type)}')")
            if uml_attr.is_static != java_field.is_static: print(f"{FAIL_MSG}: 类 {class_name} 属性 '{attr_name}': 静态性不匹配 (UML: {uml_attr.is_static}, Java: {java_field.is_static})。")
        
        for op_name_key, uml_op_list_val in uml_c.operations.items():
            is_uml_op_constructor_by_name = (op_name_key == class_name)
            java_method_candidates = [m for m in java_c.methods.get(op_name_key, []) if m.is_constructor == is_uml_op_constructor_by_name]

            for uml_op_instance in uml_op_list_val:
                is_curr_uml_op_constructor = (uml_op_instance.name == class_name) 
                matched_java_method = None; param_mismatch_details = []
                for java_m_inst in java_method_candidates:
                    params_match, detail_msg = compare_parameters(uml_op_instance.parameters, java_m_inst.parameters, class_name)
                    if params_match: matched_java_method = java_m_inst; break
                    else: param_mismatch_details.append(f"  - 对比Java方法签名 ({', '.join(p['type']+' '+p['name'] for p in java_m_inst.parameters)}): {detail_msg}")
                
                op_display_name = f"{op_name_key}({', '.join(p['type'] for p in uml_op_instance.parameters)})" # For consistent error messages

                if not matched_java_method:
                    param_details_uml = ", ".join([f"{p['type']} {p['name']}" for p in uml_op_instance.parameters])
                    op_type_str_msg = '构造' if is_curr_uml_op_constructor else ''
                    base_msg = f"{FAIL_MSG}: 类 {class_name}: UML{op_type_str_msg}操作 '{uml_op_instance.name}({param_details_uml})' 在Java中无参数匹配项。"
                    if param_mismatch_details:
                        base_msg += " 可能的参数不匹配原因:"
                        print(base_msg)
                        for d_msg in param_mismatch_details: print(d_msg)
                    else: print(f"{FAIL_MSG}: 类 {class_name}: UML{op_type_str_msg}操作 '{uml_op_instance.name}({param_details_uml})' 在Java中未找到同名且同类型的对应方法。")
                    continue
                
                jm = matched_java_method
                if uml_op_instance.visibility != jm.visibility: print(f"{FAIL_MSG}: 类 {class_name} 方法 '{op_display_name}': 可见性不匹配 (UML:{uml_op_instance.visibility}, Java:{jm.visibility})。")
                
                if is_curr_uml_op_constructor and jm.is_constructor:
                    valid_constructor_return = (are_types_equivalent(uml_op_instance.return_type, "void") or are_types_equivalent(uml_op_instance.return_type, class_name))
                    if not valid_constructor_return:
                        print(f"{FAIL_MSG}: 类 {class_name} 构造函数 '{op_display_name}': 返回类型不匹配 (UML:{uml_op_instance.return_type}, Java隐含void)。 (Normalized UML: {normalize_uml_type(uml_op_instance.return_type)}, Expected: void or {normalize_uml_type(class_name)})")
                elif not are_types_equivalent(uml_op_instance.return_type, jm.return_type):
                     print(f"{FAIL_MSG}: 类 {class_name} 方法 '{op_display_name}': 返回类型不匹配 (UML:{uml_op_instance.return_type}, Java:{jm.return_type})。(Normalized: UML '{normalize_uml_type(uml_op_instance.return_type)}', Java '{normalize_java_type_str(jm.return_type)}')")
                
                if uml_op_instance.is_static != jm.is_static: print(f"{FAIL_MSG}: 类 {class_name} 方法 '{op_display_name}': 静态性不匹配 (UML:{uml_op_instance.is_static}, Java:{jm.is_static})。")
        
        for field_name_java, java_field_instance in java_c.fields.items():
            if field_name_java not in uml_c.attributes:
                print(f"{INFO_MSG}: 类 {class_name}: Java字段 '{field_name_java}' 在UML中未找到对应属性 (允许)。")
        
        for method_key_java, java_method_list_val in java_c.methods.items():
            for java_m_instance in java_method_list_val:
                is_java_constructor = java_m_instance.is_constructor
                uml_op_name_to_find = class_name if is_java_constructor else method_key_java
                found_in_uml_fully = False
                if uml_op_name_to_find in uml_c.operations:
                    for uml_op_cand in uml_c.operations[uml_op_name_to_find]:
                        if is_java_constructor != (uml_op_cand.name == class_name): continue
                        params_match, _ = compare_parameters(uml_op_cand.parameters, java_m_instance.parameters, class_name)
                        if not params_match: continue
                        returns_match = False
                        if is_java_constructor: 
                            valid_constructor_return = (are_types_equivalent(uml_op_cand.return_type, "void") or are_types_equivalent(uml_op_cand.return_type, class_name))
                            returns_match = valid_constructor_return
                        else: returns_match = are_types_equivalent(uml_op_cand.return_type, java_m_instance.return_type)
                        if not returns_match: continue
                        if uml_op_cand.visibility == java_m_instance.visibility and uml_op_cand.is_static == java_m_instance.is_static:
                            found_in_uml_fully = True; break 
                if not found_in_uml_fully:
                    java_params_str = ", ".join([f"{p['type']}" for p in java_m_instance.parameters])
                    print(f"{INFO_MSG}: 类 {class_name}: Java{'构造' if is_java_constructor else ''}方法 '{method_key_java}({java_params_str})' UML中无完全对应操作 (允许)。")

        # --- R5: 关系检查 ---
        print(f"\n--- R5 关系检查 for class: {class_name} ---")
        java_field_details = [] 
        for f_name, f_val_assoc_check in java_c.fields.items():
            elem_type, is_coll = get_element_type_and_is_collection(f_val_assoc_check.field_type)
            if elem_type in uml_data:
                 java_field_details.append({"name": f_name, "element_type": elem_type, "is_collection": is_coll, "raw_type": f_val_assoc_check.field_type})
        associated_types_in_java_fields = {f['element_type'] for f in java_field_details}

        for assoc_info in uml_c.associations_to: 
            target_uml_name = assoc_info['target_class_name']; role_name_uml = assoc_info.get('role_name'); multiplicity_uml = assoc_info.get('multiplicity')
            uml_is_many = is_multiplicity_many(multiplicity_uml)
            found_corresponding_java_field = False
            for jf_detail in java_field_details:
                types_match = are_types_equivalent(target_uml_name, jf_detail['element_type'])
                collection_nature_matches = (uml_is_many == jf_detail['is_collection'])
                role_name_matches = (not role_name_uml) or (role_name_uml == jf_detail['name'])
                if types_match and collection_nature_matches and role_name_matches:
                    found_corresponding_java_field = True; break
            if not found_corresponding_java_field:
                print(f"{FAIL_MSG}: R5 Assoc (UML->Java) - 类 {class_name}: UML显式关联到 '{target_uml_name}' (角色:{role_name_uml or 'N/A'}, 多重性:{multiplicity_uml}, 隐含集合:{uml_is_many}) Java中无对应字段。")

        for attr_name, uml_attr in uml_c.attributes.items():
            uml_attr_elem_type, _ = get_element_type_and_is_collection(normalize_uml_type(uml_attr.attr_type))
            if uml_attr_elem_type in uml_data: 
                uml_attr_is_many = is_multiplicity_many(uml_attr.multiplicity)
                found_java_field_for_uml_attr = False
                for jf_detail in java_field_details:
                    if jf_detail['name'] == attr_name:
                        types_match = are_types_equivalent(uml_attr_elem_type, jf_detail['element_type'])
                        collection_nature_matches = (uml_attr_is_many == jf_detail['is_collection'])
                        if types_match and collection_nature_matches:
                            found_java_field_for_uml_attr = True; break
                if not found_java_field_for_uml_attr:
                    print(f"{FAIL_MSG}: R5 AttrAsAssoc (UML->Java) - 类 {class_name}: UML属性 '{attr_name}:{uml_attr.attr_type}' (多重性:{uml_attr.multiplicity}, 隐含集合:{uml_attr_is_many}, 元素类型:{uml_attr_elem_type}) (暗示关联) Java中无对应字段或类型/集合性质不匹配。")
        
        for jf_detail in java_field_details:
            is_represented_in_uml = False
            if jf_detail['name'] in uml_c.attributes:
                uml_attr_cand = uml_c.attributes[jf_detail['name']]
                uml_attr_cand_elem, _ = get_element_type_and_is_collection(normalize_uml_type(uml_attr_cand.attr_type))
                uml_attr_cand_is_many = is_multiplicity_many(uml_attr_cand.multiplicity)
                if are_types_equivalent(jf_detail['element_type'], uml_attr_cand_elem) and jf_detail['is_collection'] == uml_attr_cand_is_many:
                    is_represented_in_uml = True
            if not is_represented_in_uml:
                for assoc_info in uml_c.associations_to:
                    target_uml_name = assoc_info['target_class_name']; role_name_uml = assoc_info.get('role_name'); multiplicity_uml = assoc_info.get('multiplicity')
                    uml_assoc_is_many = is_multiplicity_many(multiplicity_uml)
                    types_match = are_types_equivalent(jf_detail['element_type'], target_uml_name)
                    collection_nature_matches = (jf_detail['is_collection'] == uml_assoc_is_many)
                    role_name_matches = (role_name_uml == jf_detail['name']) if role_name_uml else True 
                    if types_match and collection_nature_matches and role_name_matches:
                        is_represented_in_uml = True; break
            if not is_represented_in_uml:
                print(f"{FAIL_MSG}: R5 Assoc (Java->UML) - 类 {class_name}: Java字段 '{jf_detail['name']}:{jf_detail['raw_type']}' (元素类型:{jf_detail['element_type']}, 是集合:{jf_detail['is_collection']}) UML中无匹配属性或关联。")

        for dep_target_uml in uml_c.dependencies_to:
            if dep_target_uml in associated_types_in_java_fields:
                print(f"{WARN_MSG}: R5 Dep (UML->Java) - 类 {class_name}: UML依赖到 '{dep_target_uml}'，但在Java中体现为关联字段。依赖关系可能被关联覆盖或UML建模不精确。")
                continue 
            has_java_import = any(imp_path == dep_target_uml or imp_path.endswith("." + dep_target_uml) for imp_path in java_c.imports)
            has_method_sig_usage = False
            for meth_list in java_c.methods.values():
                for meth in meth_list:
                    ret_elem, _ = get_element_type_and_is_collection(meth.return_type)
                    if are_types_equivalent(dep_target_uml, ret_elem): has_method_sig_usage = True; break
                    if any(are_types_equivalent(dep_target_uml, get_element_type_and_is_collection(p['type'])[0]) for p in meth.parameters):
                        has_method_sig_usage = True; break
                if has_method_sig_usage: break
            has_textual_mention = False
            if not has_java_import and not has_method_sig_usage and java_c.filepath and os.path.exists(java_c.filepath):
                try:
                    with open(java_c.filepath, 'r', encoding='utf-8') as f_code_dep_uml:
                        java_code_content_dep_uml = f_code_dep_uml.read()
                    pattern_dep_uml = r'\b' + re.escape(dep_target_uml) + r'\b'
                    if re.search(pattern_dep_uml, java_code_content_dep_uml): has_textual_mention = True
                except IOError: pass 
            if not has_java_import and not has_method_sig_usage and not has_textual_mention:
                print(f"{FAIL_MSG}: R5 Dep (UML->Java) - 类 {class_name}: UML依赖到 '{dep_target_uml}' Java中无明显体现 (非关联, 且无imports/方法签名使用/文本提及)。")
            elif not has_java_import and not has_method_sig_usage and has_textual_mention:
                 print(f"{INFO_MSG}: R5 Dep (UML->Java) - 类 {class_name}: UML依赖到 '{dep_target_uml}' Java中仅有文本提及 (非关联, 无imports/方法签名使用)。")

        java_dep_targets_found = set()
        for imp_path in java_c.imports:
            simple_imp_name = imp_path.split('.')[-1]
            if simple_imp_name in uml_data and simple_imp_name != class_name and simple_imp_name not in associated_types_in_java_fields:
                java_dep_targets_found.add(simple_imp_name)
        for meth_list in java_c.methods.values():
            for meth in meth_list:
                ret_elem, _ = get_element_type_and_is_collection(meth.return_type)
                if ret_elem in uml_data and ret_elem != class_name and ret_elem not in associated_types_in_java_fields:
                    java_dep_targets_found.add(ret_elem)
                for p_info in meth.parameters:
                    param_elem, _ = get_element_type_and_is_collection(p_info['type'])
                    if param_elem in uml_data and param_elem != class_name and param_elem not in associated_types_in_java_fields:
                        java_dep_targets_found.add(param_elem)
        if java_c.filepath and os.path.exists(java_c.filepath):
            try:
                with open(java_c.filepath, 'r', encoding='utf-8') as f_code_java_dep:
                    java_code_content_java_dep = f_code_java_dep.read()
                for potential_dep_target in uml_data.keys(): 
                    if potential_dep_target == class_name: continue 
                    if potential_dep_target in associated_types_in_java_fields: continue 
                    if potential_dep_target in java_dep_targets_found: continue 
                    pattern_java_dep = r'\b' + re.escape(potential_dep_target) + r'\b'
                    if re.search(pattern_java_dep, java_code_content_java_dep):
                        java_dep_targets_found.add(potential_dep_target)
            except IOError: pass
        
        for dep_target_java in java_dep_targets_found:
            if dep_target_java not in uml_c.dependencies_to:
                is_attr_in_uml = any(are_types_equivalent(dep_target_java, get_element_type_and_is_collection(normalize_uml_type(ua.attr_type))[0]) for ua in uml_c.attributes.values())
                if not is_attr_in_uml:
                    source_of_java_dep = "import语句" if any(dep_target_java == imp.split('.')[-1] for imp in java_c.imports) else "方法签名" if any(are_types_equivalent(dep_target_java, get_element_type_and_is_collection(m.return_type)[0]) or any(are_types_equivalent(dep_target_java, get_element_type_and_is_collection(p['type'])[0]) for p in m.parameters) for ml in java_c.methods.values() for m in ml) else "代码内文本提及(正则)"
                    print(f"{FAIL_MSG}: R5 Dep (Java->UML) - 类 {class_name}: Java通过 ({source_of_java_dep}) 依赖于 '{dep_target_java}' (非关联类型)，但在UML中未找到对应Dependency关系 (且非同名UML属性)。")

    print("\n检查完成。")

if __name__ == "__main__":
    main()