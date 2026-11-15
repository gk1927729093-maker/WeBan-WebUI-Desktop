"""验证模型可以从中文安装路径读取，只用合成输入进行推理。"""
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

import captcha
from captcha import LoginCaptchaSolver
from client import WeBanClient


class CaptchaModelTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.original = root / "captcha_model.onnx"
        test_root = root / "build"
        test_root.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="中文安装路径 ", dir=test_root)
        directory = Path(temporary.name).resolve()
        self.assertTrue(directory.is_relative_to(test_root.resolve()))
        self.addCleanup(temporary.cleanup)
        self.model = directory / self.original.name
        self.log = Mock()
        self.enterContext(patch.object(captcha, "__file__", str(self.model.with_name("captcha.py"))))
        self.enterContext(patch.object(LoginCaptchaSolver, "_ocr", None))
        self.enterContext(patch.object(LoginCaptchaSolver, "_initialized", False))

    def test_model_loads_and_runs_from_unicode_path(self):
        shutil.copyfile(self.original, self.model)
        network = LoginCaptchaSolver.get_ocr(self.log)
        self.assertIsNotNone(network)
        network.setInput(np.zeros((1, 1, 28, 28), dtype=np.float32))
        result = network.forward()
        self.assertEqual(result.shape, (1, len(LoginCaptchaSolver._charset)))
        self.assertTrue(np.isfinite(result).all())

    def test_invalid_model_logs_the_opencv_error(self):
        self.model.write_bytes(b"invalid ONNX model")
        self.assertIsNone(LoginCaptchaSolver.get_ocr(self.log))
        self.assertIn("OpenCV DNN 无法加载验证码模型", self.log.warning.call_args.args[0])

    def test_missing_model_does_not_request_captcha_in_background(self):
        account = WeBanClient.__new__(WeBanClient)
        account.api = Mock(user={})
        account.log = self.log
        with patch("client.is_non_interactive", return_value=True):
            self.assertIsNone(account.login())
        account.api.rand_letter_image.assert_not_called()
        self.assertIn("验证码模型文件不存在", self.log.warning.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
