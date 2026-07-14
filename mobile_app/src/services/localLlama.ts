import { initLlama, LlamaContext } from 'llama.rn';
import * as FileSystem from 'expo-file-system/legacy';

let llamaContext: LlamaContext | null = null;
const API_URL = process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000';

export const getLlamaContext = async (): Promise<LlamaContext> => {
    if (llamaContext) return llamaContext;
    console.log("[LATENCY] Starting model initialization...");

    const modelName = 'gemma-2-2b-it.gguf';
    const modelPath = FileSystem.documentDirectory + modelName;

    try {
        const fileInfo = await FileSystem.getInfoAsync(modelPath);
        console.log(`Model file info: exists=${fileInfo.exists}, size=${fileInfo.exists ? fileInfo.size : 0} bytes`);

        // If it doesn't exist, it needs to be downloaded. 
        // (You might want to add a size check here once you know the exact byte size of your new model)
        if (!fileInfo.exists) {
            console.log(`Model not found locally. Downloading from ${API_URL}/public/${modelName}...`);
            console.log(`This is a large file. It will take several minutes. Please wait...`);

            const downloadResumable = FileSystem.createDownloadResumable(
                `${API_URL}/public/${modelName}`,
                modelPath,
                {},
                (downloadProgress) => {
                    const progress = downloadProgress.totalBytesWritten / downloadProgress.totalBytesExpectedToWrite;
                    // Log every 10% to avoid spamming the console too much
                    if (Math.floor(progress * 100) % 10 === 0) {
                        console.log(`Download progress: ${Math.floor(progress * 100)}%`);
                    }
                }
            );

            const downloadResult = await downloadResumable.downloadAsync();
            console.log(`Model downloaded successfully to ${downloadResult?.uri}`);
        }

        console.log("Loading model into memory...");
        // llama.rn C++ backend requires a POSIX absolute path, so we strip the 'file://' prefix
        const osPath = modelPath.startsWith('file://') ? modelPath.replace('file://', '') : modelPath;
        llamaContext = await initLlama({
            model: osPath,
            use_mlock: true,
            use_mmap: true,
            n_ctx: 512,
            n_batch: 512,
            n_gpu_layers: 0,
            n_threads: 7,
        });

        console.log(`[LATENCY] Model initialized successfully`);
        return llamaContext;
    } catch (error) {
        console.error("Failed to initialize LlamaContext", error);
        throw error;
    }
};

export const importLocalModel = async (): Promise<boolean> => {
    try {
        const DocumentPicker = require('expo-document-picker');
        const result = await DocumentPicker.getDocumentAsync({
            type: '*/*',
            copyToCacheDirectory: true,
        });

        if (result.canceled || !result.assets || result.assets.length === 0) {
            return false;
        }

        const file = result.assets[0];
        console.log("Selected file:", file.name);

        const modelName = 'gemma-2-2b-it.gguf';
        const targetPath = FileSystem.documentDirectory + modelName;

        console.log("Copying to:", targetPath);
        // Copy to document directory
        await FileSystem.copyAsync({
            from: file.uri,
            to: targetPath
        });

        console.log("Model imported successfully to:", targetPath);
        return true;
    } catch (e) {
        console.error("Failed to import model", e);
        return false;
    }
};

export const generateLocalResponse = async (
    prompt: string,
    onChunk: (text: string) => void
): Promise<string> => {
    const context = await getLlamaContext();
    const tInf = Date.now(); // Start timer AFTER the 1.6GB model is loaded into RAM

    let fullResponse = "";
    let firstToken = true;

    return new Promise((resolve, reject) => {
        context.completion(
            {
                prompt,
                n_predict: 256,
                temperature: 0.7,
                n_threads: 7,
            },
            (res) => {
                // Stream the token to the UI
                if (res.token) {
                    if (firstToken) {
                        console.log(`[LATENCY] Local LLM first token: ${Date.now() - tInf}ms`);
                        firstToken = false;
                    }
                    fullResponse += res.token;
                    onChunk(res.token);
                }
            }
        )
            .then((result) => {
                console.log(`[LATENCY] Local LLM inference: ${Date.now() - tInf}ms chars=${fullResponse.length}`);
                
                if (result && result.timings) {
                    const t = result.timings;
                    console.log(`[BENCHMARK] Prompt: ${t.prompt_n} tokens in ${t.prompt_ms.toFixed(0)}ms`);
                    console.log(`[BENCHMARK] Generation: ${t.predicted_n} tokens in ${t.predicted_ms.toFixed(0)}ms`);
                    console.log(`[BENCHMARK] Speed: ${t.predicted_per_second.toFixed(2)} tokens/sec`);
                }

                // Basic Tool Interception Logic
                // Check if the LLM outputted a JSON tool call instead of normal text
                const toolMatch = fullResponse.match(/\{[\s\S]*"name"\s*:\s*"get_(weather|current_location)"[\s\S]*\}/);

                if (toolMatch) {
                    console.log("Tool call detected in local inference!", toolMatch[0]);
                    // Note: In Task 5, we will wire this up to hit our /api/tools/execute backend endpoint!
                }

                resolve(fullResponse);
            })
            .catch((err) => {
                console.error("Local inference error:", err);
                reject(err);
            });
    });
};