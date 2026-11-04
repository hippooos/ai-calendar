#!/usr/bin/env python3
"""Prompt contract probe — chained Phase-A / Phase-B cases against the live gateway.

Install backend dependencies first. Configuration is read from environment
variables or backend/.env. No historical experiment file is required.
The script never prints the API key; running it uses live model credits.

本脚本不内嵌 Prompt 文案：始终导入并测试后端当前生产 Prompt（app/prompts/），
避免实验脚本和部署版本发生漂移。后端归一化兜底（未知字段剥离、时长钳制等）
不在本脚本内执行——本脚本只验收模型裸输出的 Prompt 效果。

Run all:    python prompt_v3_test.py
Run a batch: python prompt_v3_test.py --cases T01,T02,T03,T04
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

REFERENCE_NOW = "2026-08-30T10:00:00+08:00"
TIMEZONE = "Asia/Shanghai"

# 始终测试后端当前生产 Prompt，避免实验脚本和部署版本发生漂移。
BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
from app.prompts.phase_a import SYSTEM_PROMPT as PHASE_A_SYSTEM_PROMPT  # noqa: E402
from app.prompts.phase_b import SYSTEM_PROMPT as PHASE_B_SYSTEM_PROMPT  # noqa: E402
from app.planning.horizon import planning_window_days  # noqa: E402
from app.config import Settings  # noqa: E402

@dataclass
class Case:
    id: str
    title: str
    user_input: str
    profile: dict[str, Any]
    check: Callable[[dict[str, Any], dict[str, Any]], list[str]]

def issues_if(condition: bool, message: str) -> list[str]: return [] if condition else [message]
def item(a: dict[str, Any], kind: str = "abstract_goal") -> dict[str, Any]:
    return next((x for x in a.get("items", []) if x.get("kind") == kind), {})
def text(v: Any) -> str: return json.dumps(v, ensure_ascii=False).lower()
def prov_for(obj: dict[str, Any], path: str) -> dict[str, Any]:
    return next((p for p in obj.get("provenance", []) if p.get("field_path") == path), {})
def goals(b: dict[str, Any]) -> list[dict[str, Any]]: return b.get("goal_plans", [])
def templates(b: dict[str, Any]) -> list[dict[str, Any]]: return [t for g in goals(b) for t in g.get("task_templates", [])]

def base(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    out=[]
    if not isinstance(a.get("decision"), str): out.append("A 缺少 decision")
    if not isinstance(b.get("decision"), str): out.append("B 缺少 decision")
    if a.get("decision")=="ready" and any(x.get("kind")=="abstract_goal" for x in a.get("items",[])) and not templates(b): out.append("A 已识别抽象目标，但 B 未生成 task_templates")
    return out
def check_missing_end(a,b):
    x=item(a,"explicit_event"); return base(a,b)+issues_if(x.get("facts",{}).get("end_time") is None and x.get("facts",{}).get("duration_minutes")==60,"缺结束时间必须 end_time=null、duration=60")
def check_fixed(a,b):
    fs=b.get("fixed_events",[]); return base(a,b)+issues_if(len(fs)==1 and fs[0].get("date") and fs[0].get("start_time"),"完整明确安排必须输出一个 fixed_event")
def check_default_deadline(a,b):
    g=(goals(b)or[{}])[0]; p=g.get("deadline_provenance",{}); return base(a,b)+issues_if(a.get("decision")=="ready" and g.get("deadline") and p.get("source")=="ai_assumption" and p.get("display_label")=="AI猜测，可修改","无期限目标应有可编辑 AI 猜测截止日")
def check_complete_goal(a,b):
    ts=templates(b); return base(a,b)+issues_if(len(goals(b))==1 and len(ts)>=1 and all(t.get("activity_type") and t.get("instructions") for t in ts),"完整目标应生成一个含具体任务的计划")
def check_mixed(a,b): return base(a,b)+issues_if(len(b.get("fixed_events",[]))==1 and len(goals(b))==1,"混合输入应同时传递安排和一个目标")
def check_manual(a,b): return base(a,b)+issues_if(a.get("decision")=="manual_required" and b.get("decision")=="manual_required" and not goals(b),"安全边界必须 manual_required 且不能拆计划")
def check_profile_after_work(a,b):
    x=item(a); p=text(x.get("provenance",[])); return base(a,b)+issues_if("user_profile" in p or "system_derived" in p,"已知档案推导下班后不得当 AI 猜测")
def check_no_profile_after_work(a,b):
    x=item(a); p=text(x.get("provenance",[])); prefs=text(x.get("soft_preferences",{}))
    # 保留“下班后”原文而不虚构 18:00–22:00 同样合规；仅在补具体边界时才要求 AI 猜测标记。
    return base(a,b)+issues_if("下班后" in prefs or "ai_assumption" in p,"无档案时必须保留“下班后”原话，或将补充边界标为 AI 猜测")
def check_questions(a,b):
    qs=a.get("questions",[]); priorities=[q.get("priority") for q in qs]; return base(a,b)+issues_if(len(qs)<=3 and priorities==sorted(priorities) and all(len(q.get("missing_field",[]))<=1 if isinstance(q.get("missing_field"),list) else bool(q.get("missing_field")) for q in qs),"追问必须≤3、按优先级、每题一个缺口")
def check_weekday_hard(a,b):
    x=item(a); ts=templates(b); return base(a,b)+issues_if(x.get("hard_constraints",{}).get("allowed_weekdays")==[1,3,5] and all(t.get("hard_constraints",{}).get("allowed_weekdays")==[1,3,5] for t in ts),"明确周一三五必须作为硬约束完整保留")
def check_must_evening(a,b): return base(a,b)+issues_if("evening" in item(a).get("hard_constraints",{}).get("required_periods",[]),"“必须晚上”必须是硬约束")
def check_soft_evening(a,b):
    periods=item(a).get("soft_preferences",{}).get("preferred_periods",[])
    return base(a,b)+issues_if(any(v in periods for v in ["evening","傍晚","晚上"]),"“傍晚方便”必须是软偏好")
def check_gap(a,b): return base(a,b)+issues_if(all((t.get("min_gap_hours") or 0)>=36 for t in templates(b)),"每周三次运动必须 min_gap_hours≥36")
def check_conflict(a,b): return check_weekday_hard(a,b)+issues_if("conflict" in text(b),"硬约束与间隔冲突应被显式标记，而不是改星期")
def check_only_walk(a,b): return base(a,b)+issues_if(templates(b) and all("walk" in text(t) or "散步" in text(t) for t in templates(b)),"指定散步时不得增加或替换其他活动")
def check_suggestions(a,b):
    ts=templates(b); s=text(ts); return base(a,b)+issues_if(1<=len(ts)<=2 and all(t.get("source")=="ai_suggestion" for t in ts) and not any(w in s for w in ["称重","记录体重","复盘"]),"纯结果目标只允许1–2个 AI 建议直接行动，不能默认加记录/称重/复盘")
def check_explicit_weigh(a,b): return base(a,b)+issues_if("称重" in text(templates(b)) and "复盘" not in text(templates(b)),"用户明确要求称重时可以安排，但不可加默认复盘")
def check_one_goal(a,b): return base(a,b)+issues_if(len([x for x in a.get("items",[]) if x.get("kind")=="abstract_goal"])==1 and len(goals(b))==1,"同一结果目标及方式必须合并为一个目标")
def check_two_goals(a,b): return base(a,b)+issues_if(len(goals(b))==2,"两个独立结果目标应保留为两个目标")
def check_concrete_activity(a,b): return base(a,b)+issues_if(templates(b) and all(t.get("activity_type") and t.get("instructions") for t in templates(b)) and "30分钟运动" not in text(templates(b)),"运动任务必须是具体活动及说明")
def check_compound_trip(a,b):
    events=[x for x in a.get("items",[]) if x.get("kind")=="explicit_event"]
    categories=("请假","处理流程","注册","宣讲会")
    covered=[next((x for x in events if label in text(x)),None) for label in categories]
    distinct=len({x.get("item_id") for x in covered if x})==4
    split_ok=all(covered) and distinct and len(events)==4
    if a.get("decision")=="ready":
        fixed=b.get("fixed_events",[])
        return base(a,b)+issues_if(split_ok and len(fixed)==4 and len({x.get("source_item_id") for x in fixed})==4,
            "复合行程必须恰好拆成请假、处理流程、注册、宣讲会四项，并逐项进入 fixed_events")
    if a.get("decision")=="needs_clarification":
        return base(a,b)+issues_if(split_ok,"追问前也必须恰好拆出四个独立子活动，不得合并或漏项")
    return base(a,b)+[f"复合行程不应得到 decision={a.get('decision')}"]
def check_duration_cap(a,b):
    goal_items=[x for x in a.get("items",[]) if x.get("kind")=="abstract_goal"]
    oversized=[t for t in templates(b) if (t.get("duration_minutes") or 0)>90]
    weekend_ok=len(goal_items)==2 and all(x.get("hard_constraints",{}).get("allowed_weekdays")==[6,7] for x in goal_items)
    plans_ok=len(goals(b))==2 and all(g.get("task_templates") for g in goals(b))
    return base(a,b)+issues_if(not oversized and weekend_ok and plans_ok,
        "必须保留两个非空目标计划、给两项目标保留周末硬约束，且单任务 duration_minutes 不超过 90")
def check_pre_action_earlier(a,b):
    # v3.6：前置动作（请假等）必须排在截止日/主活动日之前；主活动排在当天。
    events=[x for x in a.get("items",[]) if x.get("kind")=="explicit_event"]
    if a.get("decision")=="needs_clarification":
        return base(a,b)+issues_if(len(events)==4,"追问前必须拆出四个子活动")
    pre=[x for x in events if "请假" in text(x)]
    main=[x for x in events if "请假" not in text(x)]
    if not pre or not main:
        return base(a,b)+issues_if(len(events)==4,"必须拆出请假与三个主活动，共四个子活动")
    pre_dates=[x.get("facts",{}).get("date") for x in pre]
    main_dates=[x.get("facts",{}).get("date") for x in main if x.get("facts",{}).get("date")]
    if not all(pre_dates) or not main_dates:
        return base(a,b)+issues_if(False,"前置动作与主活动都必须给出具体日期")
    return base(a,b)+issues_if(all(pd < min(main_dates) for pd in pre_dates if pd),
                "前置动作（请假）必须排在主活动日期之前")

P_FULL={"work_end":"18:00","sleep_start":"23:00"}
P_WORK={"work_end":"18:00"}
CASES=[
 Case("T01","明确安排缺结束","周三下午3点和客户开会",{},check_missing_end),
 Case("T02","完整明确安排","2026年9月2日15:00到16:00和客户开会",{},check_fixed),
 Case("T03","无期限减重","我要瘦5斤",{},check_default_deadline),
 Case("T04","完整目标","我想在8周内减掉5斤，每周一、周三、周五晚上散步30分钟",{},check_complete_goal),
 Case("T05","混合输入","周三下午3点和客户开会，另外我想减掉5斤",{},check_mixed),
 Case("T06","安全边界","我有心脏病，想两周内靠高强度训练瘦10斤",{},check_manual),
 Case("T07","下班后有完整档案","我想下班后散步30分钟，每周两次",P_FULL,check_profile_after_work),
 Case("T08","下班后无档案","我想下班后散步30分钟，每周两次",{},check_no_profile_after_work),
 Case("T09","下班后仅工作结束","我想下班后散步30分钟，每周两次",P_WORK,check_profile_after_work),
 Case("T10","追问排序","安排一个和客户的会议，我还想开始运动",{},check_questions),
 Case("T11","追问数量","帮我安排一个重要事情",{},check_questions),
 Case("T12","星期硬约束+晚间偏好","我想减重，每周一、周三、周五傍晚散步30分钟",{},check_weekday_hard),
 Case("T13","必须晚上","我必须每周二晚上散步30分钟",{},check_must_evening),
 Case("T14","傍晚软偏好","我傍晚比较方便，想每周散步两次",{},check_soft_evening),
 Case("T15","36小时间隔","我每周要运动3次，每次30分钟",{},check_gap),
 Case("T16","硬约束冲突保留","我只能周一、周三、周五运动，每周3次，间隔至少36小时",{},check_conflict),
 Case("T17","指定散步不加任务","为了减重，我每周散步3次，每次30分钟",{},check_only_walk),
 Case("T18","纯结果允许建议","我想减掉5斤",{},check_suggestions),
 Case("T19","明确称重允许","我每周日早上称一次体重，想减掉5斤",{},check_explicit_weigh),
 Case("T20","同目标合并","我想减重5斤，每周一三五晚上快走30分钟",{},check_one_goal),
 Case("T21","两个独立目标","我想减重5斤，也想在两个月内读完一本书",{},check_two_goals),
 Case("T22","运动必须具体","我想每周运动两次，每次30分钟",{},check_concrete_activity),
 Case("T23","散步任务保真","我想每周一三五散步30分钟",{},check_only_walk),
 Case("T24","日常安全变化","我想通过日常运动改善体力，每周两次",{},check_concrete_activity),
 Case("T25","复合行程拆解","周三前我想请假前往zz处理流程、开学注册及宣讲会",{},check_compound_trip),
 Case("T26","单任务时长上限","最近一个月我想周末都打打羽毛球和准备准备面试",{},check_duration_cap),
 Case("T27","前置动作提前一天","周三前我想请假前往A地处理流程、现场登记及宣讲会",{},check_pre_action_earlier),
]

def config() -> tuple[str,str,str|None,float]:
    settings=Settings(_env_file=BACKEND_ROOT/".env")
    base=(os.getenv("LLM_BASE_URL") or os.getenv("LITELLM_BASE_URL") or settings.llm_base_url).rstrip("/")
    model=os.getenv("LLM_MODEL") or os.getenv("LITELLM_MODEL") or settings.llm_model
    key=os.getenv("LLM_API_KEY") or os.getenv("LITELLM_API_KEY") or settings.llm_api_key
    if not base or not model: raise RuntimeError("缺少 LLM_BASE_URL/LLM_MODEL（也兼容 LITELLM_*）")
    if base.endswith("/v1"): url=base+"/chat/completions"
    elif base.endswith("/api/paas/v4"): url=base+"/chat/completions"
    else: url=base+"/v1/chat/completions"
    return url,model,key,settings.llm_timeout_seconds
def call(url:str,model:str,key:str|None,timeout_seconds:float,system:str,user:Any) -> dict[str,Any]:
    body=json.dumps({"model":model,"temperature":0,"thinking":{"type":"disabled"},"max_tokens":4096,"response_format":{"type":"json_object"},"messages":[{"role":"system","content":system},{"role":"user","content":json.dumps(user,ensure_ascii=False) if not isinstance(user,str) else user}]} ,ensure_ascii=False).encode()
    headers={"Content-Type":"application/json"}
    if key: headers["Authorization"]="Bearer "+key
    last=None
    for n in range(2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,body,headers),timeout=timeout_seconds) as res: data=json.loads(res.read().decode())
            content=data["choices"][0]["message"]["content"]
            return json.loads(content)
        except (urllib.error.URLError,urllib.error.HTTPError,KeyError,json.JSONDecodeError) as e:
            last=e; time.sleep(2*(n+1))
    raise RuntimeError(f"模型调用失败（重试2次）: {last}")
def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--cases",help="逗号分隔，例如 T01,T02"); ap.add_argument("--print-raw",action="store_true",help="同时向终端打印完整 JSON") ; args=ap.parse_args()
    selected=set(args.cases.split(",")) if args.cases else {c.id for c in CASES}; picked=[c for c in CASES if c.id in selected]
    if not picked: raise RuntimeError("未选择有效测试编号")
    url,model,key,timeout_seconds=config(); result_dir=Path(__file__).with_name("results"); result_dir.mkdir(exist_ok=True)
    print(f"Prompt v3 | model={model} | cases={','.join(c.id for c in picked)} | results={result_dir}", flush=True)
    failures=0
    for c in picked:
        print("\n"+"="*80+f"\n{c.id} {c.title}\nINPUT: {c.user_input}")
        context={"reference_now":REFERENCE_NOW,"timezone":TIMEZONE,"user_profile":c.profile,"user_input":c.user_input}
        try:
            a=call(url,model,key,timeout_seconds,PHASE_A_SYSTEM_PROMPT,context)
            b=call(url,model,key,timeout_seconds,PHASE_B_SYSTEM_PROMPT,{"reference_now":REFERENCE_NOW,"timezone":TIMEZONE,"planning_window_days":planning_window_days(c.user_input),"user_profile":c.profile,"phase_a_result":a})
            problems=c.check(a,b)
            record={"case_id":c.id,"title":c.title,"input":c.user_input,"user_profile":c.profile,"phase_a_raw_json":a,"phase_b_raw_json":b,"assertion_issues":problems}
            result_path=result_dir/f"{c.id}.json"
            result_path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
            print(f"RAW_JSON_FILE: {result_path}", flush=True)
            if args.print_raw:
                print("PHASE_A_RAW_JSON:\n"+json.dumps(a,ensure_ascii=False,indent=2), flush=True)
                print("PHASE_B_RAW_JSON:\n"+json.dumps(b,ensure_ascii=False,indent=2), flush=True)
        except Exception as exc:
            problems=[str(exc)]
            record={"case_id":c.id,"title":c.title,"input":c.user_input,"user_profile":c.profile,"phase_a_raw_json":None,"phase_b_raw_json":None,"assertion_issues":problems}
            result_path=result_dir/f"{c.id}.json"
            result_path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
            print(f"RAW_JSON_FILE: {result_path}", flush=True)
        if problems:
            failures+=1; print("RESULT: FAIL\n - "+"\n - ".join(problems))
        else: print("RESULT: PASS")
    print(f"\nSUMMARY: {len(picked)-failures}/{len(picked)} passed")
    return 1 if failures else 0
if __name__ == "__main__": raise SystemExit(main())
