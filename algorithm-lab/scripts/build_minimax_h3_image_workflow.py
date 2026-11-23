"""文件用途：从官方模板提取独立生图子图，并将其添加到现有 Pika 工作流。"""

import argparse
import copy
import json
from pathlib import Path
import uuid


# 与视频模型共用已部署的文本编码器；生图主模型与 VAE 单独加载。
DIFFUSION = "minimax_h3_image_pruned_int8_convrot.safetensors"
ENCODER = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VAE = "minimax_h3_image_vae_fp16.safetensors"
PROMPT = (
    "A photorealistic orange tabby cat resting in a relaxed sphinx pose on a soft "
    "cream blanket, both front paws fully visible and parallel, facing the camera, "
    "bright curious eyes, natural proportions, finely detailed fur and whiskers. "
    "The entire body and tail fit comfortably inside the frame with open space "
    "around the head and paws for later animation. A quiet warm living room with "
    "a simple softly blurred background, gentle daylight from the left, eye-level "
    "fixed camera, horizontal composition, realistic photography, no text."
)


def make_image_subgraph(template):
    """从官方模板提取原生生图链路；参数为模板字典，返回子图与对应外层节点。"""
    original = template["definitions"]["subgraphs"][0]
    graph = copy.deepcopy(original)
    graph["id"] = str(uuid.uuid4())
    graph["name"] = "MiniMax H3 Image 首尾帧生图"
    keep_ids = {1, 2, 3, 5, 6, 7, 8}
    graph["nodes"] = [n for n in graph["nodes"] if n["id"] in keep_ids]
    nodes = {n["id"]: n for n in graph["nodes"]}
    graph["links"] = [
        link for link in graph["links"]
        if link["origin_id"] in keep_ids
        and (link["target_id"] in keep_ids or link["target_id"] == -20)
    ]
    for node in graph["nodes"]:
        for entry in node.get("inputs", []):
            if not any(link["id"] == entry.get("link") for link in graph["links"]):
                entry["link"] = None
        for entry in node.get("outputs", []):
            entry["links"] = [
                link["id"] for link in graph["links"]
                if link["origin_id"] == node["id"]
                and node["outputs"][link["origin_slot"]] is entry
            ]

    nodes[1]["widgets_values"][0] = DIFFUSION
    nodes[1]["widgets_values_named"]["unet_name"] = DIFFUSION
    nodes[3]["widgets_values"][0] = VAE
    nodes[3]["widgets_values_named"]["vae_name"] = VAE
    nodes[2]["widgets_values"][0] = ENCODER
    nodes[2]["widgets_values_named"]["clip_name"] = ENCODER
    nodes[2]["properties"]["models"] = [{
        "name": ENCODER,
        "url": f"https://huggingface.co/Comfy-Org/MiniMax-H3-Image/resolve/main/text_encoders/{ENCODER}",
        "directory": "text_encoders",
    }]
    nodes[5]["widgets_values"] = [PROMPT, 3072, 1728]
    nodes[5]["widgets_values_named"] = {"prompt": PROMPT, "width": 3072, "height": 1728}
    nodes[7]["widgets_values"][1] = "fixed"
    nodes[7]["widgets_values_named"]["control_after_generate"] = "fixed"
    # 服务器 570 驱动不能运行权重首选的 CUDA 13 INT8 注意力内核，单独覆盖生图模型。
    backend = {
        "id": 10, "type": "ModelAttentionBackend", "pos": [540, -440],
        "size": [440, 90], "flags": {}, "order": 0, "mode": 0,
        "inputs": [
            {"name": "model", "type": "MODEL", "link": 12},
            {"name": "attention", "type": "COMBO", "widget": {"name": "attention"}, "link": None},
        ],
        "outputs": [{"name": "model", "type": "MODEL", "links": [5]}],
        "properties": {"Node name for S&R": "ModelAttentionBackend", "cnr_id": "comfy-core", "ver": "0.45.0"},
        "widgets_values": ["pytorch attention"],
        "widgets_values_named": {"attention": "pytorch attention"},
    }
    graph["nodes"].append(backend)
    nodes[1]["outputs"][0]["links"] = [12]
    next(link for link in graph["links"] if link["id"] == 5)["origin_id"] = 10
    graph["links"].append({
        "id": 12, "origin_id": 1, "origin_slot": 0,
        "target_id": 10, "target_slot": 0, "type": "MODEL",
    })

    # 模型文件固定在子图内部，避免外层 COMBO 代理缺少候选项或误用视频模型。
    # 外层只保留提示词、尺寸、种子和参考图。
    settings = [
        ("prompt", "STRING", 5, "prompt", PROMPT),
        ("width", "INT", 5, "width", 3072),
        ("height", "INT", 5, "height", 1728),
        ("seed", "INT", 7, "seed", 42),
        ("image_1", "IMAGE", 5, "images.image_1", None),
    ]
    graph["inputs"] = []
    inputs, values, named = [], [], {}
    for slot, (name, kind, target_id, target_name, value) in enumerate(settings):
        target_slot = next(i for i, entry in enumerate(nodes[target_id]["inputs"]) if entry["name"] == target_name)
        link_id = 100 + slot
        graph["links"].append({
            "id": link_id, "origin_id": -10, "origin_slot": slot,
            "target_id": target_id, "target_slot": target_slot, "type": kind,
        })
        nodes[target_id]["inputs"][target_slot]["link"] = link_id
        graph["inputs"].append({
            "id": str(uuid.uuid4()), "name": name, "type": kind,
            "linkIds": [link_id], "pos": [-966, 214 + slot * 20],
        })
        entry = {"name": name, "type": kind, "link": None}
        if kind == "IMAGE":
            entry["shape"] = 7
        else:
            entry["widget"] = {"name": name}
            values.append(value)
            named[name] = value
        inputs.append(entry)
    graph["groups"] = []
    graph["state"] = {"lastGroupId": 0, "lastNodeId": 10, "lastLinkId": 104, "lastRerouteId": 0}
    outer = {
        "id": 0, "type": graph["id"], "pos": [0, 0], "size": [540, 740],
        "flags": {}, "order": 0, "mode": 0, "title": graph["name"],
        "inputs": inputs,
        "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": []}],
        "properties": {"cnr_id": "comfy-core", "ver": "0.45.0"},
        "widgets_values": values, "widgets_values_named": named,
    }
    return graph, outer


def add_branch(workflow, graph, image_node, save_template, *, standalone=False):
    """接收原图、子图、外层节点、保存模板及独立开关，返回默认启用生图输出的新图。"""
    result = copy.deepcopy(workflow)
    if standalone:
        result = {
            "id": str(uuid.uuid4()), "revision": 0, "last_node_id": 0,
            "last_link_id": 0, "nodes": [], "links": [], "groups": [],
            "definitions": {"subgraphs": []}, "config": {}, "extra": {}, "version": 0.4,
        }
    # 合并画布默认生图；切换到视频时只需交换两个保存节点的启用状态。
    for node in result["nodes"]:
        if node["type"] == "SaveVideo":
            node["mode"] = 2
    # LiteGraph 要求主图与所有子图的节点、连线、分组编号全局唯一。
    existing_graphs = [result, *result["definitions"]["subgraphs"]]
    highest_node = max(n["id"] for g in existing_graphs for n in g["nodes"]) if result["nodes"] else 0
    highest_link = max(
        (link["id"] if isinstance(link, dict) else link[0] for g in existing_graphs for link in g["links"]),
        default=0,
    )
    highest_group = max((g.get("id", 0) for part in existing_graphs for g in part.get("groups", [])), default=0)
    image = copy.deepcopy(image_node)
    image["id"] = max(highest_node, result["last_node_id"]) + 1
    save_id = image["id"] + 1
    link_id = max(highest_link, result["last_link_id"]) + 1
    graph = copy.deepcopy(graph)
    node_ids = {n["id"]: save_id + index + 1 for index, n in enumerate(graph["nodes"])}
    link_ids = {link["id"]: link_id + index + 1 for index, link in enumerate(graph["links"])}
    for node in graph["nodes"]:
        node["id"] = node_ids[node["id"]]
        for entry in node.get("inputs", []):
            if entry.get("link") is not None:
                entry["link"] = link_ids[entry["link"]]
        for entry in node.get("outputs", []):
            entry["links"] = [link_ids[value] for value in (entry.get("links") or [])]
    for link in graph["links"]:
        link["id"] = link_ids[link["id"]]
        link["origin_id"] = node_ids.get(link["origin_id"], link["origin_id"])
        link["target_id"] = node_ids.get(link["target_id"], link["target_id"])
    for entry in graph["inputs"] + graph["outputs"]:
        entry["linkIds"] = [link_ids[value] for value in entry["linkIds"]]
    graph["state"]["lastNodeId"] = max(node_ids.values())
    graph["state"]["lastLinkId"] = max(link_ids.values())
    x, y = (0, 0) if standalone else (-3740, 4850)
    image["pos"] = [x, y]
    image["outputs"][0]["links"] = [link_id]
    save = copy.deepcopy(save_template)
    save.update({
        "id": save_id, "title": "保存首尾帧", "pos": [x + 610, y],
        "size": [600, 650], "order": 1, "mode": 0,
        "widgets_values": ["minimax_h3_image/keyframe"],
        "widgets_values_named": {"filename_prefix": "minimax_h3_image/keyframe"},
    })
    save["inputs"][0]["link"] = link_id
    result["nodes"].extend([image, save])
    result["links"].append([link_id, image["id"], 0, save_id, 0, "IMAGE"])
    result["definitions"]["subgraphs"].append(copy.deepcopy(graph))
    result["groups"].append({
        "id": highest_group + 1,
        "title": "MiniMax H3 Image 首尾帧生图", "bounding": [x - 20, y - 60, 1260, 840],
        "color": "#3f789e", "font_size": 24, "flags": {},
    })
    result["last_node_id"] = max(node_ids.values())
    result["last_link_id"] = max(link_ids.values())
    result["revision"] = result.get("revision", 0) + 1
    result["extra"]["minimax_h3_image"] = {
        "description": "文件用途：独立生成视频首尾帧，生图结果由用户选择后再载入视频工作流。",
        "source": "https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_minimax_h3_image_t2i.json",
        "comfyui": "v0.45.0", "separate_video_branch": True,
        "attention_backend": "pytorch attention",
        "fixed_models": {"unet_name": DIFFUSION, "clip_name": ENCODER, "vae_name": VAE},
        "save_node_muted": False, "active_output": "image",
    }
    if standalone:
        result["extra"]["ds"] = {"scale": 0.8, "offset": [100, 100]}
    return result


def main():
    """读取原工作流与官方模板，输出合并版和可独立运行的生图工作流。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("template", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    original = json.loads(args.original.read_text())
    template = json.loads(args.template.read_text())
    graph, outer = make_image_subgraph(template)
    save_template = next(n for n in template["nodes"] if n["type"] == "SaveImage")
    args.destination.mkdir(parents=True, exist_ok=True)
    for filename, data in [
        ("video_pika_h3_flex_fl2va.json", add_branch(original, graph, outer, save_template)),
        ("image_minimax_h3_keyframes.json", add_branch(original, graph, outer, save_template, standalone=True)),
    ]:
        (args.destination / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        print(args.destination / filename)


if __name__ == "__main__":
    main()
