# pyrefly: ignore [missing-import]
from sarvamai import SarvamAI
import os 
import requests
from dotenv import load_dotenv
load_dotenv(override=True)
api_key = os.getenv("SARVAM_API_KEY")
def main():
    client = SarvamAI(api_subscription_key=api_key)

    # Create batch job — change mode as needed
    job = client.speech_to_text_job.create_job(
        model="saaras:v3",
        mode="transcribe",
        language_code="unknown",
        with_diarization=True,
        num_speakers=2
    )

    # Upload and process files
    audio_paths = ["pooja_tts_audio.mp3", "rahul_tts_audio.mp3", "ratan_tts_audio.mp3"]
    job.upload_files(file_paths=audio_paths)
    job.start()

    # Wait for completion
    job.wait_until_complete()

    # Check file-level results
    file_results = job.get_file_results()

    print(f"\nSuccessful: {len(file_results['successful'])}")
    for f in file_results['successful']:
        print(f"  ✓ {f['file_name']}")

    print(f"\nFailed: {len(file_results['failed'])}")
    for f in file_results['failed']:
        print(f"  ✗ {f['file_name']}: {f['error_message']}")

    # Download outputs for successful files
    if file_results['successful']:
        job.download_outputs(output_dir="./output")
        print(f"\nDownloaded {len(file_results['successful'])} file(s) to: ./output")

if __name__ == "__main__":
    main()