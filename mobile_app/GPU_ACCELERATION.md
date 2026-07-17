# Mobile GPU and NPU Acceleration (LiteRT-LM)

## Current status

The app has two separate inference paths:

| Path | Where it runs | Accelerator owner |
|---|---|---|
| Backend RAG and live services | `server.py` through Ollama | The server running Ollama |
| Mobile chat generation | `src/services/localLiteRT.ts` through `LiteRTModule.kt` | The phone |

We have migrated from `llama.cpp`/`llama.rn` to Google's **LiteRT-LM** (formerly MediaPipe Tasks GenAI) to leverage native Android hardware acceleration. The mobile app now talks to a custom Kotlin Native Module that wraps the LiteRT Android SDK.

## Recommended rollout

1. **Snapdragon Devices:** LiteRT-LM will automatically try to utilize the Adreno GPU and Hexagon NPU on supported Snapdragon platforms.
2. **Fallback:** If a device does not have a supported GPU/NPU, LiteRT will elegantly fall back to CPU execution, managing threads automatically.
3. **Model Format:** We now use the `.litertlm` (or `.task`/`.bin`) format instead of `.gguf`.

## Required build changes

Because we are using a custom Native Module, the project relies on Google AI Edge LiteRT libraries.

The Android `build.gradle` has been updated with:
```gradle
implementation 'com.google.mediapipe:tasks-genai:0.10.14' // Or corresponding LiteRT-LM artifact
```

The React Native application includes:
- `LiteRTModule.kt`: Handles `initialize` and `generate` methods.
- `LiteRTPackage.kt`: Exposes the module to React Native.

**Note:** Any time the LiteRT module or dependencies change, you **must rebuild the native app** using `npx expo run:android` or by creating a new EAS build. Over-The-Air (OTA) updates cannot deliver these native changes.

## Runtime configuration

Memory management and performance tuning are handled differently with LiteRT compared to `llama.cpp`. 
Instead of manually defining `n_ctx`, `n_gpu_layers`, `use_mmap`, etc., LiteRT manages:
- Memory planning
- Tensor allocation
- Execution scheduling

You configure the high-level options inside the Native Module (e.g., `setMaxTokens(512)`). 

## Validation checklist

For every supported device and model combination:

1. Build and install a fresh native Android app.
2. Ensure the `gemma4-E2B-it.litertlm` model is hosted on your backend at `/public/gemma4-E2B-it.litertlm`.
3. Open the app, and it will download the model.
4. Record first-token latency, generated tokens/second, and verify that it utilizes the GPU (monitor via adb logcat or device metrics).
5. Verify that older or unsupported devices gracefully fall back to CPU execution.

## References

- Local inference initialization: [`src/services/localLiteRT.ts`](src/services/localLiteRT.ts)
- Native Module Implementation: [`android/app/src/main/java/com/anonymous/mobile_app/LiteRTModule.kt`](android/app/src/main/java/com/anonymous/mobile_app/LiteRTModule.kt)
