"""
STG 成本分析工具
分析不同 token 数量和模型价格下的费用节省
"""

import json
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class ModelPricing:
    """模型定价（每百万 token 的美元价格）"""
    name: str
    input_price: float  # $/M tokens
    output_price: float  # $/M tokens


# 模型定价表
MODELS = {
    "opus-4.6": ModelPricing("Claude Opus 4.6", 15.0, 75.0),
    "sonnet-4": ModelPricing("Claude Sonnet 4", 3.0, 15.0),
    "haiku-4": ModelPricing("Claude Haiku 4", 0.8, 4.0),
    "gpt-4": ModelPricing("GPT-4", 10.0, 30.0),
    "gpt-4-turbo": ModelPricing("GPT-4 Turbo", 10.0, 30.0),
    "qwen3.5-27b": ModelPricing("Qwen 3.5 27B", 0.3, 2.4),
}

# 压缩器模型（固定使用 qwen3.5-27b）
COMPRESSOR = MODELS["qwen3.5-27b"]

# STG 配置
COMPRESSION_THRESHOLD = 4096
COMPRESSION_RATIO = 0.39  # 基于实测数据
COMPRESSOR_OVERHEAD = 0.48  # 压缩器消耗 = 原始 tokens * 0.48


def calculate_cost(tokens: int, model: ModelPricing, is_input: bool = True) -> float:
    """计算成本（美元）"""
    price = model.input_price if is_input else model.output_price
    return (tokens / 1_000_000) * price


def analyze_compression_benefit(
    original_tokens: int,
    output_tokens: int,
    target_model: ModelPricing,
) -> dict:
    """
    分析压缩收益

    Args:
        original_tokens: 原始输入 token 数
        output_tokens: 输出 token 数（固定，不受压缩影响）
        target_model: 目标模型（用户实际使用的模型）

    Returns:
        包含详细分析的字典
    """
    # 场景 1: 不使用压缩
    no_compression_input_cost = calculate_cost(original_tokens, target_model, True)
    no_compression_output_cost = calculate_cost(output_tokens, target_model, False)
    no_compression_total = no_compression_input_cost + no_compression_output_cost

    # 场景 2: 使用 STG 压缩
    if original_tokens < COMPRESSION_THRESHOLD:
        # 未达到阈值，不压缩
        compression_triggered = False
        compressed_tokens = original_tokens
        compressor_tokens = 0
        compressor_cost = 0
        compressed_input_cost = calculate_cost(compressed_tokens, target_model, True)
    else:
        # 触发压缩
        compression_triggered = True
        compressed_tokens = int(original_tokens * COMPRESSION_RATIO)
        compressor_tokens = int(original_tokens * COMPRESSOR_OVERHEAD)

        # 压缩器成本（使用便宜的 qwen3.5-27b）
        compressor_cost = calculate_cost(compressor_tokens, COMPRESSOR, True)

        # 压缩后的输入成本（使用目标模型）
        compressed_input_cost = calculate_cost(compressed_tokens, target_model, True)

    # 输出成本不变
    output_cost = calculate_cost(output_tokens, target_model, False)

    # 使用压缩的总成本
    with_compression_total = compressor_cost + compressed_input_cost + output_cost

    # 计算节省
    cost_saved = no_compression_total - with_compression_total
    cost_saved_percent = (cost_saved / no_compression_total * 100) if no_compression_total > 0 else 0

    # 投资回报率（ROI）
    roi = (cost_saved / compressor_cost) if compressor_cost > 0 else 0

    return {
        "original_tokens": original_tokens,
        "output_tokens": output_tokens,
        "compression_triggered": compression_triggered,
        "compressed_tokens": compressed_tokens,
        "compressor_tokens": compressor_tokens,
        "target_model": target_model.name,
        "no_compression": {
            "input_cost": no_compression_input_cost,
            "output_cost": no_compression_output_cost,
            "total_cost": no_compression_total,
        },
        "with_compression": {
            "compressor_cost": compressor_cost,
            "compressed_input_cost": compressed_input_cost,
            "output_cost": output_cost,
            "total_cost": with_compression_total,
        },
        "savings": {
            "cost_saved": cost_saved,
            "cost_saved_percent": cost_saved_percent,
            "tokens_saved": original_tokens - compressed_tokens,
            "tokens_saved_percent": ((original_tokens - compressed_tokens) / original_tokens * 100) if original_tokens > 0 else 0,
            "roi": roi,
        }
    }


def generate_cost_curve(
    token_ranges: List[int],
    output_tokens: int,
    models: List[str],
) -> List[dict]:
    """
    生成成本曲线数据

    Args:
        token_ranges: 要测试的 token 数量列表
        output_tokens: 固定的输出 token 数
        models: 要测试的模型列表

    Returns:
        曲线数据列表
    """
    results = []

    for model_key in models:
        model = MODELS[model_key]
        for tokens in token_ranges:
            analysis = analyze_compression_benefit(tokens, output_tokens, model)
            results.append({
                "model": model_key,
                "tokens": tokens,
                "cost_without_stg": analysis["no_compression"]["total_cost"],
                "cost_with_stg": analysis["with_compression"]["total_cost"],
                "cost_saved": analysis["savings"]["cost_saved"],
                "cost_saved_percent": analysis["savings"]["cost_saved_percent"],
                "roi": analysis["savings"]["roi"],
            })

    return results


def print_analysis_table(analysis: dict):
    """打印分析表格"""
    print(f"\n{'='*80}")
    print(f"成本分析报告")
    print(f"{'='*80}")
    print(f"目标模型: {analysis['target_model']}")
    print(f"原始输入 tokens: {analysis['original_tokens']:,}")
    print(f"输出 tokens: {analysis['output_tokens']:,}")
    print(f"压缩触发: {'是' if analysis['compression_triggered'] else '否'}")

    if analysis['compression_triggered']:
        print(f"压缩后 tokens: {analysis['compressed_tokens']:,}")
        print(f"压缩器消耗: {analysis['compressor_tokens']:,}")

    print(f"\n{'-'*80}")
    print(f"{'场景':<20} {'输入成本':<15} {'输出成本':<15} {'总成本':<15}")
    print(f"{'-'*80}")

    nc = analysis['no_compression']
    print(f"{'不使用 STG':<20} ${nc['input_cost']:<14.4f} ${nc['output_cost']:<14.4f} ${nc['total_cost']:<14.4f}")

    wc = analysis['with_compression']
    if analysis['compression_triggered']:
        print(f"{'压缩器成本':<20} ${wc['compressor_cost']:<14.4f} {'-':<15} ${wc['compressor_cost']:<14.4f}")
        print(f"{'压缩后输入':<20} ${wc['compressed_input_cost']:<14.4f} {'-':<15} ${wc['compressed_input_cost']:<14.4f}")
        print(f"{'输出成本':<20} {'-':<15} ${wc['output_cost']:<14.4f} ${wc['output_cost']:<14.4f}")
    print(f"{'使用 STG 总计':<20} {'-':<15} {'-':<15} ${wc['total_cost']:<14.4f}")

    print(f"{'-'*80}")

    savings = analysis['savings']
    print(f"\n[成本节省]")
    print(f"  - 节省金额: ${savings['cost_saved']:.4f} ({savings['cost_saved_percent']:.1f}%)")
    print(f"  - 节省 tokens: {savings['tokens_saved']:,} ({savings['tokens_saved_percent']:.1f}%)")
    if analysis['compression_triggered']:
        print(f"  - ROI: {savings['roi']:.2f}x (每花费 $1 压缩，节省 ${savings['roi']:.2f})")
    print(f"{'='*80}\n")


def main():
    """主函数"""
    print("STG 成本分析工具")
    print("="*80)

    # 测试场景 1: 基于实测数据（31K tokens）
    print("\n[场景 1] 实测数据（31,077 tokens 输入）")
    print("-"*80)

    for model_key in ["opus-4.6", "sonnet-4", "gpt-4", "qwen3.5-27b"]:
        analysis = analyze_compression_benefit(31077, 1000, MODELS[model_key])
        print_analysis_table(analysis)

    # 测试场景 2: 不同 token 数量的曲线
    print("\n[场景 2] Token 数量 vs 成本节省曲线")
    print("-"*80)

    token_ranges = [2000, 4096, 8000, 16000, 32000, 64000, 128000]
    output_tokens = 1000

    curve_data = generate_cost_curve(
        token_ranges,
        output_tokens,
        ["opus-4.6", "sonnet-4", "gpt-4", "qwen3.5-27b"]
    )

    # 保存曲线数据
    with open("cost_curve_data.json", "w", encoding="utf-8") as f:
        json.dump(curve_data, f, indent=2, ensure_ascii=False)

    print("[OK] 曲线数据已保存到 cost_curve_data.json")

    # 打印摘要表格
    print("\n" + "="*120)
    print(f"{'Token 数量':<12} {'模型':<20} {'不使用 STG':<15} {'使用 STG':<15} {'节省金额':<15} {'节省比例':<12} {'ROI':<10}")
    print("="*120)

    for data in curve_data:
        print(f"{data['tokens']:<12,} {data['model']:<20} "
              f"${data['cost_without_stg']:<14.4f} ${data['cost_with_stg']:<14.4f} "
              f"${data['cost_saved']:<14.4f} {data['cost_saved_percent']:<11.1f}% "
              f"{data['roi']:<9.2f}x")

    print("="*120)


if __name__ == "__main__":
    main()
