"""文件用途：用仓库现有 H3 生图和 Pika 视频子图组装宠物加载动画工作流。"""

from copy import deepcopy
from functools import partial
from itertools import count
import json
from pathlib import Path
from uuid import UUID, uuid5


WORKFLOWS = Path(__file__).resolve().parents[1] / "workflows"
SOURCE = WORKFLOWS / "video_pika_h3_flex_fl2va.json"
OUTPUT = WORKFLOWS / "pet_loading_h3_pika.json"
FPS = 24
VIDEO_SIZE = (1024, 576)  # Pika 默认采样尺寸，成片尺寸可独立调整。
IMAGE_SIZE = (2560, 1440)
PREFIX = "pet_loading"

SCENE = (
    "Match <Picture 1> exactly outside the animals and their contact shadows. Preserve the fixed side-on camera, "
    "horizon, grass, cloud positions, daylight and semi-realistic style. "
)
PET_CAT = "a small orange tabby cat with amber eyes, white chin and dark orange stripes"
PET_DOG = "a slightly larger golden retriever with golden fur, floppy ears and no collar"
RUN_POSE = (
    "Running to screen right in a clear sideways mid-stride pose, full body and tail in frame, "
    "paws on or just above the grass, natural contact shadow. No other animals or objects."
)
IMAGE_SPECS = (
    ("01_background", "图 1 · 空白背景", 42, (),
     "Empty grass field under a blue sky with a few soft white clouds. Sky fills the upper two thirds, "
     "short green grass fills the lower third. Semi-realistic game wallpaper, soft consistent daylight, "
     "fixed low side-on wide camera, level horizon, uncluttered flat running lane. "
     "Absolutely no animals, people, buildings, paths, text, props or logos."),
    ("02_cat_dog", "图 2 · 猫狗居中奔跑", 43, ("01_background",),
     SCENE + f"Add exactly two pets in the central part of the frame: {PET_CAT}, followed by {PET_DOG}. "
     "The cat is just right of center, the dog just left of center, both on the same visible grass lane, "
     "separated without overlap. " + RUN_POSE),
    ("03_cat", "图 3 · 猫居中奔跑", 44, ("01_background", "02_cat_dog"),
     SCENE + "Add only the orange tabby from <Picture 2> at the horizontal center. Match its coat, proportions, "
     "scale and paw height. Do not include the dog. " + RUN_POSE),
    ("04_dog", "图 4 · 狗居中奔跑", 45, ("01_background", "02_cat_dog"),
     SCENE + "Add only the golden retriever from <Picture 2> at the horizontal center. Match its coat, proportions, "
     "scale and paw height. Do not include the cat. " + RUN_POSE),
)

VIDEO_SPECS = (
    ("01_intro", "先导", 3, "01_background", "02_cat_dog",
     "Start with the empty field from Picture 1. The orange tabby enters from the left and runs to the center. "
     "The golden retriever follows from the left a beat later. End in the composition of Picture 2, "
     "cat just ahead of the dog, both still running right. No pauses or fades."),
    ("02_wait_loop", "等待循环", 7, "02_cat_dog", "02_cat_dog",
     "Both pets are already running right at the start, the tabby slightly ahead. The retriever accelerates "
     "past the tabby, then the tabby accelerates back into the lead. Recover the exact positions, poses and "
     "rightward gait of Picture 1 at Picture 2 without slowing to a stop. Continuous stride through the loop seam, "
     "not a frozen or duplicated shot."),
    ("03_cat_to_dog", "猫切狗", 3, "03_cat", "04_dog",
     "Start with the tabby running at center. The golden retriever enters from the left, catches up and "
     "takes center. The tabby falls behind relative to the dog and leaves at the left edge while still running. "
     "End with only the retriever running at center; never morph one animal into the other."),
    ("04_dog_to_cat", "狗切猫", 3, "04_dog", "03_cat",
     "Start with the retriever running at center. The orange tabby enters from the left, catches up and "
     "takes center. The retriever falls behind relative to the cat and leaves at the left edge while still running. "
     "End with only the tabby running at center; never morph one animal into the other."),
)


def video_prompt(seconds, action):
    """接收成片秒数与动作描述，返回带模型首尾帧时间锚点的提示词。"""
    target = seconds * FPS
    aligned = target + (5 - target % 17) % 17  # H3 只生成 17k+5 帧。
    return (
        f"How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the "
        f"0.00-second mark; Picture 2 (from Shot 1) aligns with the {(aligned - 1) / FPS:.2f}-second mark.\n\n"
        f"integrated_multimodal_description: [Shot 1] {action} "
        "One locked-off wide side-on shot, same grass lane, horizon, sky and light throughout. "
        "Keep each pet's coat, size and anatomy stable. Distinct continuous running cycles with alternating "
        "paw contacts, no sliding or running backwards. No pan, zoom, cuts, text or logos.\n\n"
        "overall_soundscape: None.\nnon_diegetic_music: None."
    )


def set_widgets(node, **values):
    """将参数写入节点的有序和命名组件值，无返回值。"""
    node["widgets_values"] = list(values.values())
    node["widgets_values_named"] = values


def make_node(node_ids, graph, kind, title, pos, inputs, outputs, **values):
    """在指定图中创建带端口和组件参数的节点，返回节点字典。"""
    node = {
        "id": next(node_ids), "type": kind, "title": title, "pos": pos, "size": [260, 130],
        "flags": {}, "order": len(graph["nodes"]), "mode": 0,
        "properties": {"cnr_id": "comfy-core", "ver": "0.45.0", "Node name for S&R": kind},
        "inputs": [{"name": name, "type": dtype, "link": None, **(
            {"widget": {"name": name}} if name in values else {}
        )} for name, dtype in inputs],
        "outputs": [{"name": name, "type": dtype, "links": []} for name, dtype in outputs],
    }
    set_widgets(node, **values)
    graph["nodes"].append(node)
    return node


def connect(link_ids, graph, source, output, target, input_name):
    """按端口连接节点；空节点表示子图输入或输出，无返回值。"""
    outputs = graph["inputs"] if source is None else source["outputs"]
    inputs = graph["outputs"] if target is None else target["inputs"]
    slot = next(index for index, port in enumerate(inputs) if port["name"] == input_name)
    link_id = next(link_ids)
    output_port, input_port = outputs[output], inputs[slot]
    out_key = "linkIds" if source is None else "links"
    output_port[out_key] = (output_port.get(out_key) or []) + [link_id]
    if target is None:
        input_port["linkIds"].append(link_id)
    else:
        input_port["link"] = link_id
    origin = -10 if source is None else source["id"]
    destination = -20 if target is None else target["id"]
    data = [link_id, origin, output, destination, slot, output_port["type"]]
    keys = ("id", "origin_id", "origin_slot", "target_id", "target_slot", "type")
    graph["links"].append(dict(zip(keys, data)) if "inputNode" in graph else data)


def prepare_video(graph, defaults, add, wire):
    """保留 Pika 核心采样链并接入定帧导出；参数为子图、权重和构图函数，无返回值。"""
    retained_ports = (0, 3, 4, 11, 12)
    graph["name"] = "Pika H3 首尾帧成片"
    graph["inputs"] = [graph["inputs"][index] for index in retained_ports]
    for port, label in zip(graph["inputs"], ("动作提示词", "成片秒数", "种子", "首帧", "尾帧")):
        port["label"] = label
    graph["nodes"] = [node for node in graph["nodes"] if node["id"] not in {120, 121, 150, 151, 152, 153}]
    nodes = {node["id"]: node for node in graph["nodes"]}
    graph["links"] = [link for link in graph["links"] if (
        (link["origin_id"] in nodes or (link["origin_id"] == -10 and link["origin_slot"] in retained_ports))
        and link["target_id"] in nodes and link["id"] != 167
    )]
    live_links = {link["id"] for link in graph["links"]}
    for link in graph["links"]:
        if link["origin_id"] == -10:
            link["origin_slot"] = retained_ports.index(link["origin_slot"])
    for node in nodes.values():
        for port in node["inputs"]:
            if port.get("link") not in live_links:
                port["link"] = None
        for port in node["outputs"]:
            port["links"] = [link for link in (port.get("links") or []) if link in live_links]
    graph["outputs"][0]["linkIds"] = []
    width, height = VIDEO_SIZE
    set_widgets(nodes[119], vae_name=defaults["vae_name"])
    set_widgets(nodes[127], unet_name=defaults["unet_name"], weight_dtype="default")
    set_widgets(nodes[129], noise_seed=2718, control_after_generate="fixed")
    set_widgets(nodes[131], prompt=video_prompt(3, VIDEO_SPECS[0][-1]), width=width, height=height, length=73)
    nodes[130].update(pos=[300, 4660], title="采样帧序列", size=[265, 190])
    video_output, image_output = [("VIDEO", "VIDEO")], [("IMAGE", "IMAGE")]
    video_input = [("video", "VIDEO")]
    math_inputs = [("values.a", "FLOAT,INT,BOOLEAN"), ("expression", "STRING")]
    math_outputs = [("FLOAT", "FLOAT"), ("INT", "INT"), ("BOOL", "BOOLEAN")]
    frame_count = add(graph, "ComfyMathExpression", "成片帧数", [310, 5000],
                      math_inputs, math_outputs, expression=f"round(a * {FPS})")
    sample = add(graph, "VideoFrameSample", "均匀采样（保留模型首尾帧）", [620, 4660], video_input + [
        ("num_frames", "INT"), ("strategy", "COMBO"), ("seed", "INT")], video_output,
        num_frames=72, strategy="uniform", seed=0)
    unpack = add(graph, "GetVideoComponents", "取出画面帧", [930, 4660], video_input,
                 image_output + [("audio", "AUDIO"), ("fps", "FLOAT"), ("bit_depth", "COMBO"), ("color_space", "COMBO")])
    scale_inputs = [("image", "IMAGE"), ("upscale_method", "COMBO"), ("width", "INT"),
                    ("height", "INT"), ("crop", "COMBO")]
    scale_options = {"upscale_method": "bicubic", "width": 1920, "height": 1080, "crop": "center"}
    scale = add(graph, "ImageScale", "调整模型帧尺寸", [1240, 4660], scale_inputs, image_output, **scale_options)
    encode = add(graph, "CreateVideo", "24 fps 无声成片", [1550, 4660], [("images", "IMAGE")],
                 video_output, **nodes[130]["widgets_values_named"])
    encode["size"] = [265, 190]
    wire(graph, nodes[133], 0, frame_count, "values.a")
    wire(graph, nodes[122], 0, nodes[130], "images")
    wire(graph, nodes[130], 0, sample, "video")
    wire(graph, frame_count, 1, sample, "num_frames")
    wire(graph, sample, 0, unpack, "video")
    wire(graph, unpack, 0, scale, "image")
    wire(graph, scale, 0, encode, "images")
    wire(graph, encode, 0, None, "VIDEO")
    graph["groups"][-1].update(title="模型帧采样与导出", bounding=[-80, 4540, 1920, 650])
    graph["outputNode"]["bounding"] = [1870, 4650, 128, 68]
    graph["outputs"][0]["pos"] = [1894, 4674]


def expose_video_resolution(workflow):
    """在现有工作流上添加尺寸控件，保留其他节点和设定，无返回值。"""
    graphs = workflow["definitions"]["subgraphs"]
    graph = next(part for part in graphs if any(node["type"] == "MiniMaxH3ImageToVideo" for node in part["nodes"]))
    sampler = next(node for node in graph["nodes"] if node["type"] == "MiniMaxH3ImageToVideo")
    scales = [node for node in graph["nodes"] if node["type"] == "ImageScale"]
    dimension_specs = (
        ("width", "采样宽度", "width", sampler, True),
        ("height", "采样高度", "height", sampler, True),
        ("output_width", "成片宽度", "width", scales[0], False),
        ("output_height", "成片高度", "height", scales[0], False),
    )
    add = partial(make_node, count(workflow["last_node_id"] + 1))
    wire = partial(connect, count(workflow["last_link_id"] + 1))
    box = graph["inputNode"]["bounding"]
    box[3] = max(box[3], 48 + 20 * (len(graph["inputs"]) + len(dimension_specs)))
    new_values = {}
    for index, (name, label, axis, default_node, align) in enumerate(dimension_specs):
        value = default_node["widgets_values_named"][axis]
        new_values[name] = value
        slot = len(graph["inputs"])
        graph["inputs"].append({"id": str(uuid5(UUID(graph["id"]), name)), "name": name, "label": label,
                                "type": "INT", "linkIds": [], "pos": [box[0] + box[2] - 24, box[1] + 24 + slot * 20]})
        pos = [-1320 + index * 310, 4300]
        dimension = add(graph, "PrimitiveInt", label, pos, [("value", "INT")], [("INT", "INT")],
                        value=value, control_after_generate="fixed")
        wire(graph, None, slot, dimension, "value")
        if align:
            # H3 的采样尺寸必须对齐到 32；与原 FL2VA 保持一致。
            aligned = add(graph, "ComfyMathExpression", f"{label}对齐", [pos[0], pos[1] + 150],
                          [("values.a", "FLOAT,INT,BOOLEAN"), ("expression", "STRING")],
                          [("FLOAT", "FLOAT"), ("INT", "INT"), ("BOOL", "BOOLEAN")],
                          expression="max(32, round(a / 32) * 32)")
            wire(graph, dimension, 0, aligned, "values.a")
            wire(graph, aligned, 1, sampler, axis)
        else:
            for scale in scales:
                wire(graph, dimension, 0, scale, axis)

    for node in workflow["nodes"]:
        if node["type"] == graph["id"]:
            node["inputs"].extend({"name": name, "type": "INT", "widget": {"name": name}, "link": None}
                                  for name in new_values)
            set_widgets(node, **node["widgets_values_named"], **new_values)
            node["size"][1] = max(node["size"][1], 280)
    workflow.update(last_node_id=max(node["id"] for node in graph["nodes"]),
                    last_link_id=max(link["id"] for link in graph["links"]))
    for part in graphs:
        part["state"].update(lastNodeId=workflow["last_node_id"], lastLinkId=workflow["last_link_id"])


def build_workflow(template):
    """接收已部署模型同源的模板，返回包含四图和四视频的可导入工作流。"""
    image_graph, video_graph = (deepcopy(graph) for graph in reversed(template["definitions"]["subgraphs"]))
    templates = {node["type"]: node for node in template["nodes"]}
    image_template, video_template = templates[image_graph["id"]], templates[video_graph["id"]]
    add = partial(make_node, count(200))
    wire = partial(connect, count(300))
    prepare_video(video_graph, video_template["widgets_values_named"], add, wire)

    reference = deepcopy(image_graph["inputs"][-1])
    reference.update(id="5b675cb6-d849-4d45-a671-c618812d5321", name="image_2", label="角色参考",
                     pos=[reference["pos"][0], reference["pos"][1] + 20], linkIds=[])
    image_graph["inputs"][-1]["label"] = "背景参考"
    image_graph["inputs"].append(reference)
    condition = next(node for node in image_graph["nodes"] if node["type"] == "MiniMaxH3ImageConditioning")
    wire(image_graph, None, 5, condition, "images.image_2")

    workflow = {
        "id": "139ae813-7018-4b04-8ff5-9f9845a709f8", "revision": 0, "version": 0.4, "config": {},
        "nodes": [], "links": [], "groups": [], "definitions": {"subgraphs": [image_graph, video_graph]},
        "extra": {"frontendVersion": template["extra"]["frontendVersion"],
                  "description": "文件用途：生成宠物壁纸的四张关键帧和四段首尾帧加载动画。",
                  "ds": {"scale": 0.6, "offset": [75, 100]}},
    }
    instance_ids = count(20)

    def instance(node_template, title, pos, size, **values):
        node = deepcopy(node_template)
        node.update(id=next(instance_ids), title=title, pos=pos, size=size, order=len(workflow["nodes"]))
        for port in node.get("inputs", []):
            port["link"] = None
        for port in node.get("outputs", []):
            port["links"] = []
        set_widgets(node, **values)
        workflow["nodes"].append(node)
        return node

    image_nodes = {}
    for index, (name, title, seed, refs, prompt) in enumerate(IMAGE_SPECS):
        column, row = (0, 1) if index == 0 else (500, index - 1)
        top = row * 400
        node = instance(image_template, title, [column, top], [450, 220],
                        prompt=prompt, width=IMAGE_SIZE[0], height=IMAGE_SIZE[1], seed=seed)
        node["inputs"].append({"name": "image_2", "type": "IMAGE", "shape": 7, "link": None})
        for slot, ref in enumerate(refs, 1):
            wire(workflow, image_nodes[ref], 0, node, f"image_{slot}")
        save = instance(templates["SaveImage"], f"保存{title[:3]}", [column, top + 245], [450, 130],
                        filename_prefix=f"{PREFIX}/keyframes/{name}")
        wire(workflow, node, 0, save, "images")
        image_nodes[name] = node

    for index, (name, title, seconds, first, last, action) in enumerate(VIDEO_SPECS):
        top = index * 290
        label = f"{title} · {seconds}s"
        node = instance(video_template, label, [1050, top], [510, 240],
                        prompt=video_prompt(seconds, action), value_1=seconds, noise_seed=2718 + index)
        node["inputs"] = [port for port in node["inputs"] if port["name"] in {"prompt", "value_1", "noise_seed", "first_frame", "last_frame"}]
        wire(workflow, image_nodes[first], 0, node, "first_frame")
        wire(workflow, image_nodes[last], 0, node, "last_frame")
        save = instance(templates["SaveVideo"], f"保存{label}", [1620, top], [390, 230],
                        filename_prefix=f"{PREFIX}/video/{name}", format="auto", **{"format.codec": "auto", "codec": "auto"})
        save["mode"] = 2  # 导入后默认只出关键帧；视频可逐段启用。
        wire(workflow, node, 0, save, "video")

    for group_id, title, bounds, color in (
        (10, "① 空白背景与三张角色关键帧", [-25, -60, 1000, 1240], "#3f789e"),
        (11, "② 首尾帧动画 · 按需启用右侧保存节点", [1025, -60, 1010, 1200], "#477c60"),
    ):
        workflow["groups"].append({"id": group_id, "title": title, "bounding": bounds,
                                   "color": color, "font_size": 24, "flags": {}})
    graphs = [workflow, image_graph, video_graph]
    max_node = max(node["id"] for graph in graphs for node in graph["nodes"])
    max_link = max(link["id"] if isinstance(link, dict) else link[0] for graph in graphs for link in graph["links"])
    workflow.update(last_node_id=max_node, last_link_id=max_link)
    for graph in (image_graph, video_graph):
        graph["state"].update(lastNodeId=max_node, lastLinkId=max_link, lastGroupId=11)
    expose_video_resolution(workflow)
    return workflow


if __name__ == "__main__":
    workflow = build_workflow(json.loads(SOURCE.read_text(encoding="utf-8")))
    OUTPUT.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
