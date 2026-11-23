"""文件用途：检查宠物加载工作流的可复现性、子图连线和首尾帧复用。"""

import json

from scripts.build_pet_loading_workflow import OUTPUT, SOURCE, build_workflow


def test_loading_workflow_links():
    """验证导出文件与生成器一致，且各图的端口和链接双向对应。"""
    workflow = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert workflow == build_workflow(json.loads(SOURCE.read_text(encoding="utf-8")))
    node_ids, link_ids = set(), set()
    for graph in [workflow, *workflow["definitions"]["subgraphs"]]:
        nodes = {node["id"]: node for node in graph["nodes"]}
        assert len(nodes) == len(graph["nodes"])
        assert node_ids.isdisjoint(nodes)
        node_ids.update(nodes)
        for node in nodes.values():
            for key in ("inputs", "outputs"):
                names = [port["name"] for port in node.get(key, [])]
                assert len(names) == len(set(names))
        for link in graph["links"]:
            keys = ("id", "origin_id", "origin_slot", "target_id", "target_slot", "type")
            link_id, origin, output, target, input_slot, dtype = (
                [link[key] for key in keys] if isinstance(link, dict) else link
            )
            assert link_id not in link_ids
            link_ids.add(link_id)
            if origin == -10:
                source = graph["inputs"][output]
                assert link_id in source["linkIds"]
            else:
                source = nodes[origin]["outputs"][output]
                assert link_id in source["links"]
            assert dtype in source["type"].split(",")
            if target == -20:
                dest = graph["outputs"][input_slot]
                assert link_id in dest["linkIds"]
            else:
                dest = nodes[target]["inputs"][input_slot]
                assert link_id == dest["link"]
            assert dtype in dest["type"].split(",")


def test_loading_workflow_reuses_keyframes():
    """验证角色图参考关系、视频方向、时长与默认静音状态。"""
    workflow = json.loads(OUTPUT.read_text(encoding="utf-8"))
    image_graph, video_graph = workflow["definitions"]["subgraphs"]
    links = {link[0]: link[1] for link in workflow["links"]}

    def connected_sources(node, *ports):
        return tuple(links.get(port["link"]) for port in node["inputs"] if port["name"] in ports)

    background, duo, cat, dog = [node for node in workflow["nodes"] if node["type"] == image_graph["id"]]
    assert connected_sources(background, "image_1", "image_2") == (None, None)
    assert connected_sources(duo, "image_1", "image_2") == (background["id"], None)
    for single in (cat, dog):
        assert connected_sources(single, "image_1", "image_2") == (background["id"], duo["id"])

    videos = [node for node in workflow["nodes"] if node["type"] == video_graph["id"]]
    assert len(videos) == 4
    for node, (seconds, first, last) in zip(videos, ((3, background, duo), (7, duo, duo), (3, cat, dog), (3, dog, cat))):
        assert node["widgets_values_named"]["value_1"] == seconds
        assert connected_sources(node, "first_frame", "last_frame") == (first["id"], last["id"])
    assert [node["mode"] for node in workflow["nodes"] if node["type"] == "SaveImage"] == [0] * 4
    assert [node["mode"] for node in workflow["nodes"] if node["type"] == "SaveVideo"] == [2] * 4


def test_video_resolution_controls():
    """检查逐段尺寸控件支持独立采样和导出，三个导出缩放节点共用成片宽高。"""
    workflow = json.loads(OUTPUT.read_text(encoding="utf-8"))
    graph = workflow["definitions"]["subgraphs"][1]
    nodes = {node["id"]: node for node in graph["nodes"]}
    links = {link["id"]: link for link in graph["links"]}

    def source(node, input_name):
        port = next(port for port in node["inputs"] if port["name"] == input_name)
        return links[port["link"]]

    expected = {"width": 1024, "height": 576, "output_width": 1920, "output_height": 1080}
    for node in workflow["nodes"]:
        if node["type"] == graph["id"]:
            assert {key: node["widgets_values_named"][key] for key in expected} == expected
            assert {port["name"] for port in node["inputs"] if "widget" in port} >= expected.keys()
    sampler = next(node for node in nodes.values() if node["type"] == "MiniMaxH3ImageToVideo")
    scales = [node for node in nodes.values() if node["type"] == "ImageScale"]
    assert len(scales) == 3
    for axis in ("width", "height"):
        aligner = nodes[source(sampler, axis)["origin_id"]]
        assert aligner["type"] == "ComfyMathExpression"
        assert aligner["widgets_values_named"]["expression"] == "max(32, round(a / 32) * 32)"
        sample_size = nodes[source(aligner, "values.a")["origin_id"]]
        export_ids = {source(scale, axis)["origin_id"] for scale in scales}
        assert len(export_ids) == 1
        export_size = nodes[export_ids.pop()]
        for node, name in ((sample_size, axis), (export_size, f"output_{axis}")):
            link = source(node, "value")
            assert link["origin_id"] == -10
            assert graph["inputs"][link["origin_slot"]]["name"] == name
