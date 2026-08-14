# -*- coding: utf-8 -*-
"""
ActionRunner - 按顺序执行 Action 列表。

支持：
- 顺序执行
- 单步失败时收集 error 并可选择继续/中断
- 把结果写入 ActionContext.variables（Action 通过 into 指定）
"""


class ActionRunner:
    def __init__(self, ctx):
        self.ctx = ctx

    def run(self, actions, stop_on_error: bool = True) -> dict:
        """
        执行动作列表。
        Returns:
            {'success': bool, 'results': [逐动作结果], 'errors': [逐动作异常信息]}
        """
        results = []
        errors = []
        success = True
        for action in actions:
            try:
                result = action.execute(self.ctx)
                results.append(result)
                errors.append(None)
            except Exception as e:
                errors.append(f'{action.name}: {e}')
                results.append(None)
                if stop_on_error:
                    success = False
                    break
        return {
            'success': success and not any(errors),
            'results': results,
            'errors': errors,
        }
