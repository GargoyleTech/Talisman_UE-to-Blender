"""Unreal Engine Texture: native image sampling with an embedded package browser."""

import uuid

import bpy

from . import texture_browser as browser
from ..language import strings


def image_changed(node, _context):
    if node.node_tree and (image_node := node.node_tree.nodes.get("Unreal Image")):
        image_node.image = node.image


def sampling_changed(node, _context):
    if node.node_tree and (image_node := node.node_tree.nodes.get("Unreal Image")):
        image_node.interpolation = node.interpolation
        image_node.extension = node.extension


class SQEX_ShaderNodeUnrealTexture(bpy.types.ShaderNodeCustomGroup):
    bl_idname = browser.NODE_TYPE
    bl_label = "Unreal Engine Texture"
    bl_description = strings.TEXTURE_BROWSER_NODE
    bl_icon = "IMAGE_DATA"
    bl_width_default = 360
    bl_width_min = 240
    bl_width_max = 1000

    browser_id: bpy.props.StringProperty(options={"HIDDEN"})
    game_key: bpy.props.StringProperty(default=browser.NONE, options={"HIDDEN"})
    game: bpy.props.EnumProperty(name="Game", description=strings.TEXTURE_BROWSER_GAME,
                                 items=browser.game_items, get=browser.game_get, set=browser.game_set,
                                 update=browser.game_changed)
    browser_open: bpy.props.BoolProperty(name="Browse Textures", default=True,
                                         description=strings.TEXTURE_BROWSER_EXPAND)
    browser_entries: bpy.props.CollectionProperty(type=browser.SQEX_PG_texture_browser_entry, options={"SKIP_SAVE"})
    active_index: bpy.props.IntProperty(default=-1, min=-1, update=browser.highlight_changed, options={"SKIP_SAVE"})
    directory: bpy.props.StringProperty(options={"SKIP_SAVE"})
    search: bpy.props.StringProperty(name="Search", description=strings.TEXTURE_BROWSER_SEARCH,
                                    options={"TEXTEDIT_UPDATE", "SKIP_SAVE"}, update=browser.search_changed)
    browser_page: bpy.props.IntProperty(default=0, min=0, options={"SKIP_SAVE"})
    browser_message: bpy.props.StringProperty(options={"SKIP_SAVE"})
    show_preview: bpy.props.BoolProperty(name="Preview", default=True, description=strings.TEXTURE_BROWSER_PREVIEW,
                                        update=browser.highlight_changed)
    image: bpy.props.PointerProperty(type=bpy.types.Image, update=image_changed)
    interpolation: bpy.props.EnumProperty(name="Interpolation", items=(
        ("Linear", "Linear", ""), ("Closest", "Closest", ""), ("Cubic", "Cubic", ""), ("Smart", "Smart", "")),
        default="Linear", update=sampling_changed)
    extension: bpy.props.EnumProperty(name="Extension", items=(
        ("REPEAT", "Repeat", ""), ("EXTEND", "Extend", ""), ("CLIP", "Clip", ""), ("MIRROR", "Mirror", "")),
        default="REPEAT", update=sampling_changed)

    def init(self, _context):
        self.browser_id = uuid.uuid4().hex
        prefs = browser.preferences()
        last = prefs.texture_browser_last_game if prefs else browser.NONE
        self.game_key = last if any(key == last for key, _label in browser.game_choices()) else browser.NONE
        tree = bpy.data.node_groups.new("Unreal Engine Texture", "ShaderNodeTree")
        self.node_tree = tree
        vector = tree.interface.new_socket(name="Vector", in_out="INPUT", socket_type="NodeSocketVector")
        vector.hide_value = True
        tree.interface.new_socket(name="Color", in_out="OUTPUT", socket_type="NodeSocketColor")
        tree.interface.new_socket(name="Alpha", in_out="OUTPUT", socket_type="NodeSocketFloat")
        group_input = tree.nodes.new("NodeGroupInput")
        group_input.location = (-260, 0)
        image = tree.nodes.new("ShaderNodeTexImage")
        image.name = "Unreal Image"
        image.location = (0, 0)
        output = tree.nodes.new("NodeGroupOutput")
        output.location = (300, 0)
        tree.links.new(image.outputs["Color"], output.inputs["Color"])
        tree.links.new(image.outputs["Alpha"], output.inputs["Alpha"])

    def copy(self, node):
        self.browser_id = uuid.uuid4().hex
        if node.node_tree:
            self.node_tree = node.node_tree.copy()
        self.browser_entries.clear()
        self.active_index = -1

    def free(self):
        current = browser._STATES.pop(self.browser_id, None)
        if current:
            current.close()
        tree = self.node_tree
        if tree and tree.users <= 1:
            bpy.data.node_groups.remove(tree)

    def update(self):
        # An unconnected Vector must retain native Image Texture UV behavior.
        # Only route the group socket when the outer socket has a real link.
        tree = self.node_tree
        if not tree or not self.inputs or not (image := tree.nodes.get("Unreal Image")):
            return
        vector = image.inputs["Vector"]
        linked = self.inputs["Vector"].is_linked
        if linked and not vector.is_linked:
            group_input = next(node for node in tree.nodes if node.type == "GROUP_INPUT")
            tree.links.new(group_input.outputs["Vector"], vector)
        elif not linked and vector.is_linked:
            for link in list(vector.links):
                tree.links.remove(link)

    def draw_buttons(self, context, layout):
        current = browser._STATES.get(self.browser_id)
        row = layout.row()
        row.enabled = not current or current.batch is None
        row.prop(self, "game", text="Game")
        if self.browser_message:
            import textwrap
            for line in textwrap.wrap(self.browser_message, width=40):
                layout.label(text=line, icon="INFO")
        if self.game_key != browser.NONE:
            row = layout.row(align=True)
            row.prop(self, "browser_open", text="Browse Textures", emboss=False,
                     icon="TRIA_DOWN" if self.browser_open else "TRIA_RIGHT")
            browser._button(row, "node.sqex_texture_popup", self, text="", icon="FULLSCREEN_ENTER")
            if self.browser_open:
                browser.draw_browser(layout, context, self)
        if self.image:
            layout.template_ID(self, "image", open="image.open")
            row = layout.row(align=True)
            row.prop(self, "interpolation", text="")
            row.prop(self, "extension", text="")
            layout.prop(self.image.colorspace_settings, "name", text="Color Space")


CLASSES = (SQEX_ShaderNodeUnrealTexture,)
