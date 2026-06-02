import sys
import os
import asyncio
import json

backend_dir = r"c:\Users\AnilMutalik\OneDrive - Motiveminds Consulting Pvt Ltd\Desktop\CleanCore AI\backend"
sys.path.insert(0, backend_dir)

from services.orchestrator import orchestrator
from models import InputSource

async def main():
    print("Testing orchestrator pipeline on z_atc_s4_readiness_ecc_fixture...")
    
    # Read the saved fixture source
    fixture_path = os.path.join(backend_dir, "fixture_source.abap")
    if not os.path.exists(fixture_path):
        print(f"Error: Fixture source file not found at {fixture_path}")
        return
        
    with open(fixture_path, "r", encoding="utf-8") as f:
        source_code = f.read()
        
    print(f"Loaded source code ({len(source_code)} characters). Running pipeline...")
    
    session = await orchestrator.run_full_pipeline(
        source_code=source_code,
        object_name="Z_ATC_S4_READINESS_ECC_FIXTURE",
        input_source=InputSource.FILE_UPLOAD
    )
    
    print("\n--- Pipeline Run Summary ---")
    print(f"Session ID: {session.id}")
    print(f"Status: {session.status}")
    print(f"Total Findings: {session.total_findings}")
    print(f"Fixes Generated: {session.fixes_generated}")
    print(f"Tokens Used: {session.tokens_used}")
    
    print("\n--- Findings Generated ---")
    for idx, f in enumerate(session.findings):
        print(f"Finding {idx+1}: Line {f.line} | Category: {f.category.value} | Title: {f.check_title} | Msg: {f.message}")
        
    print("\n--- Fixes Generated ---")
    for idx, fix in enumerate(session.fixes):
        print(f"\nFix {idx+1}: Finding ID: {fix.finding_id}")
        print(f"Category: {fix.category.value} | Priority: {fix.priority.value} | Worker: {fix.worker_type}")
        print(f"Confidence: {fix.confidence:.2f} | Tier: {fix.tier.value}")
        print("Original:")
        print(fix.original_code[:200] + "...")
        print("Fixed:")
        print(fix.fixed_code[:200] + "...")
        print(f"Rationale: {fix.rationale}")
        print(f"Requires Human Review: {fix.requires_human_review}")
        
    # Check if obsolete table was processed by LLM
    vbuk_fixes = [f for f in session.fixes if f.category.value == "obsolete_table"]
    if vbuk_fixes:
        print("\n[SUCCESS] Obsolete table fixes were processed!")
    else:
        print("\n[WARNING] No obsolete table fixes were processed. Check specialized_workers.py.")

if __name__ == "__main__":
    asyncio.run(main())
