#!/usr/bin/env python3
"""Capture the real path renderers with synthetic inputs, without a car or manager.

Run from a built desktop UI environment (raylib headless, Pillow):
  python tools/visuals/preview_blue_path.py --output /tmp/blue-path-preview
"""
import argparse
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  if Path('/AGNOS').exists() or Path('/TICI').exists():
    parser.error('Run this synthetic preview on a development computer.')
  args.output.mkdir(parents=True, exist_ok=True)
  root = Path(__file__).resolve().parents[2]
  for directory in (root, root / 'opendbc_repo', root / 'msgq_repo', root / 'tinygrad_repo'):
    sys.path.insert(0, str(directory))

  shm_root = '/tmp' if sys.platform == 'darwin' else '/dev/shm'
  with (tempfile.TemporaryDirectory(prefix='blue-path-params-') as params_dir,
        tempfile.TemporaryDirectory(prefix='msgq_blue-path-', dir=shm_root) as messaging_dir):
    os.environ.update(RAYLIB_BACKEND='headless', BIG='1', SCALE='1', FPS='20', PARAMS_ROOT=params_dir,
                      OPENPILOT_PREFIX=Path(messaging_dir).name.removeprefix('msgq_'))
    import numpy as np
    import pyray as rl
    from PIL import Image
    from openpilot.common.params import Params
    from openpilot.system.ui.lib.application import gui_app
    from openpilot.system.ui.lib.multilang import multilang

    params = Params()
    # Test the persisted default before selecting the new style.
    assert params.get('RainbowModeStyle', return_default=True) == 0
    params.put('LanguageSetting', 'zh-CHT', block=True)
    params.put_bool('RainbowMode', True, block=True)
    params.put('RainbowModeStyle', 1, block=True)
    multilang.change_language('zh-CHT')
    gui_app.init_window('Synthetic native path preview')

    from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
    from openpilot.selfdrive.ui.onroad.model_renderer import ModelRenderer
    from openpilot.selfdrive.ui.mici.onroad.model_renderer import ModelRenderer as MiciRenderer
    from openpilot.selfdrive.ui.sunnypilot.layouts.settings.visuals import VisualsLayout
    from openpilot.system.ui.widgets.label import gui_label
    from openpilot.system.ui.lib.shader_polygon import draw_polygon

    def capture():
      image = rl.load_image_from_screen()
      try:
        rl.image_format(image, rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8)
        return Image.frombytes('RGBA', (image.width, image.height), bytes(rl.ffi.buffer(image.data, image.width * image.height * 4)))
      finally:
        rl.unload_image(image)

    ui_state.rainbow_path = True
    ui_state.status = UIStatus.ENGAGED
    ui_state.started_frame = 0

    class PreviewMessages(dict):
      pass

    renderer = ModelRenderer()
    rect = rl.Rectangle(0, 0, 2160, 1080)
    scenarios = {'rainbow': (0, 0.0, False), 'accelerating': (1, 1.2, False),
                 'decelerating': (1, -1.2, False), 'stopping': (1, -1.2, True), 'steady': (1, 0.0, False)}
    labels = {'rainbow': '彩虹道路', 'accelerating': '加速', 'decelerating': '減速', 'stopping': '模型預計停止', 'steady': '等速'}

    for name, (style, acceleration, stopping) in scenarios.items():
      ui_state.rainbow_mode_style = style
      renderer.blue_path.reset()
      x = np.linspace(2.0, 30.0 if stopping else 80.0, 33)
      raw = np.c_[x, 0.002 * x ** 2, np.zeros_like(x)].astype(np.float32)
      renderer._rect = rect
      renderer._clip_region = rl.Rectangle(-500, -500, 3160, 2080)
      renderer.set_transform(np.array([[1080, 1300, 0], [140, 0, 1300], [1, 0, 0]], dtype=np.float32))
      renderer._path.raw_points = raw
      renderer._path.projected_points = renderer._map_line_to_polygon(raw, 0.9, renderer._path_offset_z, len(x) - 1, x[-1], False)
      frames = []
      for i in range(16):
        now = 100.0 + i * 0.1
        t = np.linspace(0, 10, 33)
        velocity = np.full(33, 10.0)
        if stopping:
          velocity[28:] = 0.0
        md = SimpleNamespace(position=SimpleNamespace(x=x, t=t), velocity=SimpleNamespace(x=velocity, t=t),
                             action=SimpleNamespace(shouldStop=False))
        sm = PreviewMessages(carState=SimpleNamespace(aEgo=acceleration, vEgo=10.0), modelV2=md,
                             longitudinalPlan=SimpleNamespace(allowThrottle=True))
        sm.valid = dict.fromkeys((*sm, 'selfdriveStateSP'), True)
        sm.valid['selfdriveStateSP'] = False
        sm.alive = dict.fromkeys(sm, True)
        sm.recv_frame = dict.fromkeys(sm, 20)
        sm.recv_time = dict.fromkeys(sm, now)
        ui_state.sm = sm
        rl.begin_drawing()
        rl.clear_background(rl.Color(32, 38, 45, 255))
        for side in (-1.8, 1.8):
          lane = raw.copy()
          lane[:, 1] += side
          points = renderer._map_line_to_polygon(lane, 0.045, renderer._path_offset_z, len(x) - 1, x[-1])
          draw_polygon(rect, points, rl.Color(194, 203, 211, 190))
        with patch('openpilot.selfdrive.ui.sunnypilot.onroad.blue_path.time.monotonic', return_value=now):
          renderer._draw_path(sm)
        gui_label(rl.Rectangle(80, 40, 1900, 70), labels[name], font_size=50)
        gui_label(rl.Rectangle(80, 960, 1900, 60), 'NATIVE RENDERER / SYNTHETIC INPUT', font_size=36, color=rl.Color(182, 196, 210, 255))
        rl.end_drawing()
        frames.append(capture().convert('RGB').resize((864, 432), Image.Resampling.LANCZOS))
      frames[-1].save(args.output / (name + '.png'))
      if name in ('accelerating', 'decelerating'):
        assert np.any(np.asarray(frames[0])[80:360] != np.asarray(frames[10])[80:360]), 'Animated chevrons must be visible'
      gif_frames = [frame.resize((640, 320), Image.Resampling.LANCZOS).quantize(colors=64) for frame in frames]
      gif_path = args.output / (name + '.gif')
      gif_frames[0].save(gif_path, save_all=True, append_images=gif_frames[1:], duration=100, loop=0, optimize=False)
      with Image.open(gif_path) as saved:
        assert saved.size == (640, 320)

    # Exercise the second production renderer with an offset viewport.
    mici = MiciRenderer()
    mici._rect = rl.Rectangle(180, 80, 1800, 900)
    mici._path = renderer._path
    mici._clip_region = renderer._clip_region
    mici.set_transform(renderer._car_space_transform)
    ui_state.rainbow_mode_style = 1
    rl.begin_drawing()
    rl.clear_background(rl.BLACK)
    with patch('openpilot.selfdrive.ui.sunnypilot.onroad.blue_path.time.monotonic', return_value=now):
      mici._draw_path(sm)
    rl.end_drawing()
    capture().save(args.output / 'mici-offset.png')

    # The real setting controls, including persistence and master-toggle disablement.
    visuals = VisualsLayout()
    for text in ('啟用 Tesla 彩虹道路模式', '彩虹道路', '動態藍條', '模型預計停止'):
      font = gui_app.fallback_font(text)
      assert all(c.isspace() or font.glyphs[rl.get_glyph_index(font, ord(c))].value == ord(c) for c in text), text
    visuals._update_state()
    assert visuals._rainbow_style.action_item.selected_button == 1
    assert visuals._rainbow_style.action_item.enabled
    params.put_bool('RainbowMode', False, block=True)
    visuals._update_state()
    assert not visuals._rainbow_style.action_item.enabled
    params.put_bool('RainbowMode', True, block=True)
    for _ in range(3):
      rl.begin_drawing()
      rl.clear_background(rl.BLACK)
      visuals.render(rl.Rectangle(40, 40, 2080, 1000))
      rl.end_drawing()
    capture().save(args.output / 'settings.png')
    gui_app.close()
    print('Native renderer and settings checks passed:', args.output)


if __name__ == '__main__':
  main()
