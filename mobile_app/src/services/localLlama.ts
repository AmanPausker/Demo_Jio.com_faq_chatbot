import { initLlama, LlamaContext } from 'llama.rn';
import * as FileSystem from 'expo-file-system/legacy';

let llamaContext: LlamaContext | null = null;
const API_URL = process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000';

export const getLlamaContext = async (): Promise<LlamaContext> => {
    if (llamaContext) return llamaContext;
    console.log("[LATENCY] Starting model initialization...");

    // Assuming the GGUF model is downloaded to the app's document directory.
    // In a real app, you'd add a download screen before reaching this point.
    const modelPath = FileSystem.documentDirectory + 'gemma-2-2b-it.gguf';

    try {
        const fileInfo = await FileSystem.getInfoAsync(modelPath);
        console.log(`Model file info: exists=${fileInfo.exists}, size=${fileInfo.exists ? fileInfo.size : 0} bytes`);

        // The Gemma 2 2B model is roughly 1.6 GB 
        // If it exists but is smaller than 1.5 GB, it was a partial download and needs to be redownloaded.
        if (!fileInfo.exists || fileInfo.size < 1500000000) {
            console.log(`Model not found locally. Downloading from ${API_URL}/public/gemma-2-2b-it.gguf...`);
            console.log(`This is a 1.6GB file. It will take several minutes. Please wait...`);

            const downloadResumable = FileSystem.createDownloadResumable(
                `${API_URL}/public/gemma-2-2b-it.gguf`,
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
            n_ctx: 1024,      
            n_gpu_layers: 0,
            n_threads: 8,     // Reverted to 8 as 4 was slower on Moto G85
        });

        console.log(`[LATENCY] Model initialized successfully`);
        return llamaContext;
    } catch (error) {
        console.error("Failed to initialize LlamaContext", error);
        throw error;
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
                n_threads: 8,     
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
            .then(() => {
                console.log(`[LATENCY] Local LLM inference: ${Date.now() - tInf}ms chars=${fullResponse.length}`);

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