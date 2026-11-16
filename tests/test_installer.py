"""检查安装包的数据边界、升级标识和卸载行为，不读实际账号凭据。"""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer_builder', ROOT / 'installer' / 'build_msi.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
NS = {'w': builder.WIX_NS}


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.test_root = (ROOT / 'logs' / 'installer-tests').resolve()
        self.test_root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=self.test_root)
        self.folder = Path(self.temporary.name).resolve()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.assertTrue(self.folder.is_relative_to(self.test_root))
        self.temporary.cleanup()

    def make_wix(self, name):
        stage = self.folder / name
        stage.mkdir()
        (stage / 'WeBanWebUI.exe').write_bytes(b'TEST')
        (stage / 'app').mkdir()
        (stage / 'app' / 'webui.py').write_text('TEST', encoding='utf-8')
        target = self.folder / (name + '.wxs')
        builder.write_wix(stage, target)
        return ET.parse(target)

    def test_installer_defaults_have_no_accounts_or_credentials(self):
        config = builder.default_config()
        self.assertEqual(config['account'], [])
        self.assertFalse(config['ai']['enable'])
        self.assertEqual(config['ai']['api_key'], '')
        self.assertEqual(config['settings']['exam_mode'], 'true')
        self.assertNotIn('config.toml', builder.APPLICATION_FILES)
        self.assertFalse(any(name.startswith(('logs/', '.git/')) for name in builder.APPLICATION_FILES))

    def test_source_archive_can_build_with_the_verified_public_question_bank(self):
        (self.folder / 'answer').mkdir()
        public = (ROOT / 'answer' / 'answer.json').read_bytes().replace(b'\r\n', b'\n')
        (self.folder / 'answer' / 'answer.json').write_bytes(public)
        self.assertEqual(builder.read_public_answers(self.folder), public)

    def test_changed_local_question_bank_is_rejected_without_git_baseline(self):
        (self.folder / 'answer').mkdir()
        (self.folder / 'answer' / 'answer.json').write_text('{"local_runtime_data":true}', encoding='utf-8')
        with self.assertRaises(RuntimeError):
            builder.read_public_answers(self.folder)

    def test_upgrade_and_component_guids_are_stable_across_build_paths(self):
        first, second = self.make_wix('first'), self.make_wix('second')
        self.assertEqual(first.find('w:Product', NS).get('UpgradeCode'), second.find('w:Product', NS).get('UpgradeCode'))
        self.assertEqual([item.get('Guid') for item in first.findall('.//w:Component', NS)],
                         [item.get('Guid') for item in second.findall('.//w:Component', NS)])

    def test_per_user_install_has_start_stop_and_data_shortcuts(self):
        tree = self.make_wix('payload')
        package = tree.find('w:Product/w:Package', NS)
        self.assertEqual(package.get('InstallScope'), 'perUser')
        self.assertEqual(package.get('InstallPrivileges'), 'limited')
        shortcuts = tree.findall('.//w:Shortcut', NS)
        self.assertEqual(len(shortcuts), 4)
        self.assertIn('--stop', [item.get('Arguments') for item in shortcuts])
        self.assertIn('--open-data', [item.get('Arguments') for item in shortcuts])
        self.assertTrue(all(item.get('Root') == 'HKCU' for item in tree.findall('.//w:RegistryValue', NS)))

    def test_uninstall_uses_embedded_launcher_and_does_not_remove_user_data(self):
        tree = self.make_wix('payload')
        binary = tree.find('w:Product/w:Binary[@Id="DesktopStopLauncher"]', NS)
        self.assertEqual(binary.get('SourceFile'), '$(var.StageDir)\\WeBanWebUI.exe')
        action = tree.find('w:Product/w:CustomAction', NS)
        self.assertEqual(action.get('ExeCommand'),
                         '--stop --quiet --data-dir "[LocalAppDataFolder]WeBanWebUI\\Data" '
                         '--installed-directory "[INSTALLFOLDER]."')
        self.assertEqual(action.get('Return'), 'check')
        self.assertEqual(action.get('BinaryKey'), 'DesktopStopLauncher')
        self.assertIsNone(action.get('FileKey'))
        self.assertEqual(tree.find('.//w:Custom', NS).text, 'Installed AND REMOVE="ALL"')
        self.assertFalse(any('Data' == item.get('Name') for item in tree.findall('.//w:Directory', NS)))
        self.assertFalse(tree.findall('.//w:RemoveFile', NS))

    def test_custom_install_directory_is_remembered_for_uninstall_and_upgrade(self):
        tree = self.make_wix('payload')
        directory = tree.find('w:Product/w:Property[@Id="INSTALLFOLDER"]', NS)
        self.assertEqual(directory.get('Secure'), 'yes')
        search = directory.find('w:RegistrySearch', NS)
        self.assertEqual(search.get('Name'), 'InstallDirectory')
        values = tree.findall('.//w:RegistryValue', NS)
        self.assertTrue(any(item.get('Name') == 'InstallDirectory' and item.get('Value') == '[INSTALLFOLDER]' for item in values))

    def test_embedded_runtime_does_not_copy_pip_or_cached_bytecode(self):
        source, target = self.folder / 'site', self.folder / 'target'
        (source / 'demo' / '__pycache__').mkdir(parents=True)
        (source / 'pip').mkdir()
        (source / 'demo' / 'module.py').write_text('TEST', encoding='utf-8')
        (source / 'demo' / '__pycache__' / 'module.pyc').write_bytes(b'PRIVATE_PATH')
        (source / 'pip' / 'module.py').write_text('TEST', encoding='utf-8')
        builder.copy_site_packages(source, target)
        self.assertTrue((target / 'demo' / 'module.py').is_file())
        self.assertFalse((target / 'demo' / '__pycache__').exists())
        self.assertFalse((target / 'pip').exists())

    def test_dependency_archive_cannot_extract_outside_target_directory(self):
        archive = self.folder / 'bad.zip'
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('../outside.txt', 'TEST')
        with self.assertRaises(RuntimeError):
            builder.extract(archive, self.folder / 'extracted')
        self.assertFalse((self.folder / 'outside.txt').exists())


if __name__ == '__main__':
    unittest.main()
