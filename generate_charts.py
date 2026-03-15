"""
生成 STG 成本分析图表
"""

import json
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # 使用非交互式后端

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# 读取数据
with open('cost_curve_data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 按模型分组
models = {}
for item in data:
    model = item['model']
    if model not in models:
        models[model] = []
    models[model].append(item)

# 模型显示名称
model_names = {
    'opus-4.6': 'Claude Opus 4.6',
    'sonnet-4': 'Claude Sonnet 4',
    'gpt-4': 'GPT-4',
    'qwen3.5-27b': 'Qwen 3.5 27B'
}

# 颜色方案
colors = {
    'opus-4.6': '#FF6B6B',
    'sonnet-4': '#4ECDC4',
    'gpt-4': '#45B7D1',
    'qwen3.5-27b': '#96CEB4'
}

# 图表 1: 成本对比（所有模型）
fig, ax = plt.subplots(figsize=(14, 8))

for model_key, items in models.items():
    tokens = [item['tokens'] for item in items]
    cost_without = [item['cost_without_stg'] for item in items]
    cost_with = [item['cost_with_stg'] for item in items]

    ax.plot(tokens, cost_without, 'o--', label=f'{model_names[model_key]} (No STG)',
            color=colors[model_key], alpha=0.6, linewidth=2)
    ax.plot(tokens, cost_with, 'o-', label=f'{model_names[model_key]} (With STG)',
            color=colors[model_key], linewidth=2.5)

ax.set_xlabel('Token Count', fontsize=12, fontweight='bold')
ax.set_ylabel('Cost (USD)', fontsize=12, fontweight='bold')
ax.set_title('STG Cost Comparison Across Models', fontsize=14, fontweight='bold')
ax.legend(loc='upper left', fontsize=10)
ax.grid(True, alpha=0.3)
ax.set_xscale('log')
ax.set_yscale('log')

plt.tight_layout()
plt.savefig('cost_comparison_all_models.png', dpi=300, bbox_inches='tight')
print("[OK] Generated: cost_comparison_all_models.png")

# 图表 2: 节省比例曲线
fig, ax = plt.subplots(figsize=(14, 8))

for model_key, items in models.items():
    tokens = [item['tokens'] for item in items]
    saved_percent = [item['cost_saved_percent'] for item in items]

    ax.plot(tokens, saved_percent, 'o-', label=model_names[model_key],
            color=colors[model_key], linewidth=2.5, markersize=8)

ax.set_xlabel('Token Count', fontsize=12, fontweight='bold')
ax.set_ylabel('Cost Savings (%)', fontsize=12, fontweight='bold')
ax.set_title('STG Cost Savings Percentage by Token Count', fontsize=14, fontweight='bold')
ax.legend(loc='lower right', fontsize=11)
ax.grid(True, alpha=0.3)
ax.axhline(y=0, color='red', linestyle='--', alpha=0.5)
ax.set_xscale('log')

plt.tight_layout()
plt.savefig('savings_percentage_curve.png', dpi=300, bbox_inches='tight')
print("[OK] Generated: savings_percentage_curve.png")

# 图表 3: ROI 对比
fig, ax = plt.subplots(figsize=(14, 8))

for model_key, items in models.items():
    tokens = [item['tokens'] for item in items if item['roi'] > 0]
    roi = [item['roi'] for item in items if item['roi'] > 0]

    if roi:  # 只绘制有 ROI 的数据
        ax.plot(tokens, roi, 'o-', label=model_names[model_key],
                color=colors[model_key], linewidth=2.5, markersize=8)

ax.set_xlabel('Token Count', fontsize=12, fontweight='bold')
ax.set_ylabel('ROI (Return on Investment)', fontsize=12, fontweight='bold')
ax.set_title('STG Return on Investment by Model', fontsize=14, fontweight='bold')
ax.legend(loc='upper right', fontsize=11)
ax.grid(True, alpha=0.3)
ax.axhline(y=1, color='red', linestyle='--', alpha=0.5, label='Break-even (ROI=1)')
ax.set_xscale('log')

plt.tight_layout()
plt.savefig('roi_comparison.png', dpi=300, bbox_inches='tight')
print("[OK] Generated: roi_comparison.png")

# 图表 4: Opus 4.6 详细分析
opus_data = models['opus-4.6']
tokens = [item['tokens'] for item in opus_data]
cost_without = [item['cost_without_stg'] for item in opus_data]
cost_with = [item['cost_with_stg'] for item in opus_data]
cost_saved = [item['cost_saved'] for item in opus_data]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

# 左图：成本对比
ax1.bar([str(t) for t in tokens], cost_without, alpha=0.6, label='Without STG', color='#FF6B6B')
ax1.bar([str(t) for t in tokens], cost_with, alpha=0.8, label='With STG', color='#4ECDC4')
ax1.set_xlabel('Token Count', fontsize=12, fontweight='bold')
ax1.set_ylabel('Cost (USD)', fontsize=12, fontweight='bold')
ax1.set_title('Claude Opus 4.6: Cost Comparison', fontsize=13, fontweight='bold')
ax1.legend(fontsize=10)
ax1.grid(True, alpha=0.3, axis='y')
ax1.tick_params(axis='x', rotation=45)

# 右图：节省金额
ax2.bar([str(t) for t in tokens], cost_saved, color='#96CEB4', alpha=0.8)
ax2.set_xlabel('Token Count', fontsize=12, fontweight='bold')
ax2.set_ylabel('Cost Saved (USD)', fontsize=12, fontweight='bold')
ax2.set_title('Claude Opus 4.6: Absolute Savings', fontsize=13, fontweight='bold')
ax2.grid(True, alpha=0.3, axis='y')
ax2.tick_params(axis='x', rotation=45)

# 在柱子上添加数值标签
for i, v in enumerate(cost_saved):
    if v > 0:
        ax2.text(i, v, f'${v:.2f}', ha='center', va='bottom', fontsize=9)

plt.tight_layout()
plt.savefig('opus_detailed_analysis.png', dpi=300, bbox_inches='tight')
print("[OK] Generated: opus_detailed_analysis.png")

print("\n[SUCCESS] All charts generated successfully!")
print("Files created:")
print("  - cost_comparison_all_models.png")
print("  - savings_percentage_curve.png")
print("  - roi_comparison.png")
print("  - opus_detailed_analysis.png")
