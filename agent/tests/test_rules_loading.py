from app.rules.loader import RuleLoader


def test_rule_loading_and_update(tmp_path):
    rules_dir = tmp_path / 'rules'
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / 'runtime_rules.yaml').write_text('version: 1\nname: runtime\n', encoding='utf-8')

    loader = RuleLoader(rules_dir)
    all_rules = loader.load_all()
    assert 'runtime_rules.yaml' in all_rules

    payload = {'version': 2, 'name': 'runtime', 'constraints': ['a']}
    loader.save_rule_file('runtime_rules.yaml', payload)
    loaded = loader.load_rule_file('runtime_rules.yaml')
    assert loaded['version'] == 2
