压缩的方式:

````
原始 messages:
  [system]  "You are a helpful assistant..."        ← 保留
  [user]    "解释 CAP 定理"                          ← 旧，压缩
  [assistant] "CAP 定理是分布式系统..."（2000字）     ← 旧，压缩
  [user]    "举个实际例子"                            ← 旧，压缩
  [assistant] "比如 DynamoDB 选择了 AP..."（1500字）   ← 旧，压缩
  [user]    "那和 BASE 有什么关系"                    ← 旧，压缩
  [assistant] "BASE 理论是..."（1800字）              ← 最近，保留
  [user]    "总结一下"                               ← 最近，保留
                                                      ← 最近无 assistant

压缩后 messages:
  [system]    "You are a helpful assistant..."       ← 原封不动
  [assistant] "[对话摘要] 用户询问了 CAP 定理、实际     ← qwen3.5-27b 生成的摘要
               案例（DynamoDB AP 选择）、以及 BASE
               理论与 CAP 的关系..."
  [user]      "总结一下"                              ← 原封不动

压缩的详细策略
当旧的历史信息超过阈值(4000token)启动压缩 如在上述的例子中:
  [user]    "解释 CAP 定理"                          ← 旧，压缩
  [assistant] "CAP 定理是分布式系统..."（2000字）     ← 旧，压缩
  [user]    "举个实际例子"                            ← 旧，压缩
  [assistant] "比如 DynamoDB 选择了 AP..."（1500字）   ← 旧，压缩
  [user]    "那和 BASE 有什么关系"                    ← 旧，压缩
  
  这部分信息需要压缩

然后会产生新的信息 如:

[system]    "You are a helpful assistant..."       ← 原封不动
  [assistant] "[对话摘要] 用户询问了 CAP 定理、实际     ← qwen3.5-27b 生成的摘要
               案例（DynamoDB AP 选择）、以及 BASE
               理论与 CAP 的关系..."
  [assistant] "BASE 理论是..."（1800字）              
  [user]      "总结一下"                              
  [assistant] "总结..." (3000字)
  [user]      "新的问题XXX"
  
  这时候可以看到:
[assistant] "BASE 理论是..."（1800字）              
  [user]      "总结一下"                              
  [assistant] "总结..." (3000字)
  又超过了阈值 所以这部分也同样的进行总结 并合并入
  
  [assistant] "[对话摘要] 用户询问了 CAP 定理、实际     ← qwen3.5-27b 生成的摘要
               案例（DynamoDB AP 选择）、以及 BASE
               理论与 CAP 的关系..."中
               
   如果 此时[对话摘要] 未超过阈值 则忽略 如果超过了 那在对[对话摘要]进行一次总结 

注意 总结时候要结合用户最新的命令 保留历史关键信息  但是也不要过于的冗长 总结之后的长度 不超过30%的阈值
````

````
 1.2. 问题: "最近 2 轮"的定义不够清晰

 是这样:
原始 messages:
  [system]  "You are a helpful assistant..."        ← 保留
  [user]    "解释 CAP 定理"                          ← 旧，压缩
  [assistant] "CAP 定理是分布式系统..."（2000字）     ← 旧，压缩
  [user]    "举个实际例子"                            ← 旧，压缩
  [assistant] "比如 DynamoDB 选择了 AP..."（2500字）   ← 旧，压缩
  [user]    "那和 BASE 有什么关系"                    ← 旧，压缩
  [assistant] "BASE 理论是..."（1800字）              ← 最近，保留
  [user]    "总结一下"    
  
  
 检测到:
  [user]    "解释 CAP 定理"                          ← 旧，压缩
  [assistant] "CAP 定理是分布式系统..."（2000字）     ← 旧，压缩
  [user]    "举个实际例子"                            ← 旧，压缩
  [assistant] "比如 DynamoDB 选择了 AP..."（2500字）   ← 旧，压缩
  [user]    "那和 BASE 有什么关系"                    ← 旧，压缩
  超出了阈值进行压缩 -> "[对话摘要] 用户询问了 CAP 定理、实际     ← qwen3.5-27b 生成的摘要
               案例（DynamoDB AP 选择）、以及 BASE
               理论与 CAP 的关系..."
               
接下来
 [system]    "You are a helpful assistant..."       ← 原封不动
    [assistant] "[对话摘要] 用户询问了 CAP 定理、实际     ← qwen3.5-27b 生成的摘要
               案例（DynamoDB AP 选择）、以及 BASE
               理论与 CAP 的关系..."(400字)
    [assistant] "BASE 理论是..."（1800字）              
    [user]      "总结一下"                              
    [assistant] "总结..." (3000字)
    [user]      "新的问题1XXX"
    [assistant] "新问题1的回答XXX" (2000字)
    [user]      "新的问题2XXX"
    
    此时:
    [assistant] "BASE 理论是..."（1800字）              
    [user]      "总结一下"                              
    [assistant] "总结..." (3000字)
    超过了阈值 进行压缩-> 新的压缩结果 "[对话摘要2]..."
    和"[对话摘要] 用户询问了 CAP 定理、实际     ← qwen3.5-27b 生成的摘要
       案例（DynamoDB AP 选择）、以及 BASE
       理论与 CAP 的关系..." 合并 得到:

       "[对话摘要] 用户询问了 CAP 定理、实际     ← qwen3.5-27b 生成的摘要
       案例（DynamoDB AP 选择）、以及 BASE
       理论与 CAP 的关系...
        [对话摘要2]..."
        
        如果上面的这个新的对话摘要 超出了阈值 那么对其再次进行压缩 此时的压缩策略是 对于越久远的对话摘要可以更加省略可以忽略index默认模型不需要调用久远的对话的原始数据 对于最近的对话摘要较为详细的summary 得到新的对话摘要
        
        最终:
        
    [system]    "You are a helpful assistant..."       ← 原封不动
    [assistant] "[对话摘要] 用户询问了 CAP 定理、实际     ← qwen3.5-27b 生成的摘要
                   案例（DynamoDB AP 选择）、以及 BASE
                   理论与 CAP 的关系...
                    [对话摘要2]..."
    [assistant] "新问题1的回答XXX" (2000字)
    [user]      "新的问题2XXX"

 


  3. 摘要的存储位置

	作为一条特殊的 system message


  4. History Index 的追加策略

  文档说"更新 History Index（追加新的旧消息）"，但：
  摘要本身被再次压缩，原来的摘要内容还是保存逻辑不变 


  5. 二次压缩的触发时机

	是超过了阈值本身 而不是30% 30%是压缩后的可接受的上限

  6. 压缩成本预估的时机

  文档提到"在压缩前评估：压缩成本 C vs 预期节省 S"，但：
  - 对于多轮压缩，如何计算预期节省？
  - 摘要再生成的成本如何计算？
计算成本 就是原始输入的token - 压缩后的输入 即可 多轮压缩也与 原始一次都没有压缩的token进行比较
  
````

````
 1. 配置文件中的压缩参数

  忽略现有代码中的参数 以及代码 我们要重新开发

  2. 摘要的 role 字段

  只保留当前agent的system prompt 非当前agent的system prompt 不要传入
  摘要应该用特殊的 role（如 "assistant"）但内容以 [对话摘要] 开头

  3. 压缩后的 messages 顺序

  根据你的示例，压缩后的结构是：
  [system]  "You are a helpful assistant..."
  [system]  "[对话摘要] ..."
  [assistant] "BASE 理论是..."
  [user]    "总结一下"
  
  如果这样1.5轮有问题(比如api报错) 那就:
  [system]  "You are a helpful assistant..."
  [assistant]  "[对话摘要] ..."
  [user]    "BASE 理论是什么"
  [assistant] "BASE 理论是..."
  [user]    "总结一下"
  

  4. L1 缓存的匹配逻辑

	不要使用embedding 而是就使用缓存的idx 在压缩后的每条后面附带一个idx, 如:
"[对话摘要] 用户询问了 CAP 定理、实际     ← qwen3.5-27b 生成的摘要[idx]
                   案例（DynamoDB AP 选择）、以及 BASE
                   理论与 CAP 的关系[idx]...
                    [对话摘要2]...[idx]"



  5. 工具注入的时机

	每次都注入 判断

  请确认这些问题，我会继续完善文档！
````

