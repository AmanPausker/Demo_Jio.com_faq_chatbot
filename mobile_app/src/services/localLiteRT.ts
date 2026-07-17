import { NativeModules, NativeEventEmitter } from 'react-native';
import * as FileSystem from 'expo-file-system/legacy';

const { LiteRTModule } = NativeModules;
const LiteRTEventEmitter = new NativeEventEmitter(LiteRTModule);

let isInitialized = false;
const API_URL = process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000';
export const getLiteRTContext = async (): Promise<boolean> => {
    if (isInitialized) return true;
    console.log('\r\x1b[36m LOG  [LATENCY] Starting LiteRT model initialization...\x1b[0m');

    const modelName = 'gemma4-E2B-it.litertlm';
    const modelPath = FileSystem.documentDirectory + modelName;

    try {
        let fileInfo = await FileSystem.getInfoAsync(modelPath);
        console.log(`Model file info: exists=${fileInfo.exists}, size=${fileInfo.exists ? fileInfo.size : 0} bytes`);

        if (fileInfo.exists && fileInfo.size < 100 * 1024 * 1024) {
            console.log("Existing model file is too small (corrupted/404). Deleting it...");
            await FileSystem.deleteAsync(modelPath);
            fileInfo.exists = false;
        }

        if (!fileInfo.exists) {
            console.log(`Model not found locally. Downloading from ${API_URL}/public/${modelName}...`);
            console.log(`This is a large file. It will take several minutes. Please wait...`);

            const downloadResumable = FileSystem.createDownloadResumable(
                `${API_URL}/public/${modelName}`,
                modelPath,
                {},
                (downloadProgress) => {
                    const progress = downloadProgress.totalBytesWritten / downloadProgress.totalBytesExpectedToWrite;
                    if (Math.floor(progress * 100) % 10 === 0) {
                        console.log(`Download progress: ${Math.floor(progress * 100)}%`);
                    }
                }
            );

            const downloadResult = await downloadResumable.downloadAsync();
            if (downloadResult && downloadResult.status !== 200) {
                await FileSystem.deleteAsync(modelPath);
                throw new Error(`Failed to download model. Server returned status: ${downloadResult.status}`);
            }
            console.log(`\r\x1b[36m LOG  Model downloaded successfully to ${downloadResult?.uri}\x1b[0m`);
        }

        console.log("Loading model into LiteRT memory...");
        const osPath = modelPath.startsWith('file://') ? modelPath.replace('file://', '') : modelPath;

        // Native Module Initialization
        await LiteRTModule.initialize(osPath);
        isInitialized = true;

        console.log(`[LATENCY] LiteRT Model initialized successfully via AI Edge`);
        return true;
    } catch (error) {
        console.error("Failed to initialize LiteRT", error);
        throw error;
    }
};

export const resetLiteRTConversation = async (): Promise<boolean> => {
    try {
        await LiteRTModule.resetConversation();
        console.log('\r\x1b[36m LOG  [LATENCY] LiteRT Conversation history cleared.\x1b[0m');
        return true;
    } catch (error) {
        console.error("Failed to reset LiteRT conversation", error);
        return false;
    }
};

export const abortLocalGeneration = async (): Promise<boolean> => {
    try {
        await LiteRTModule.abortGeneration();
        return true;
    } catch (error) {
        console.error("Failed to abort generation", error);
        return false;
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

        const modelName = 'gemma4-E2B-it.litertlm';
        const targetPath = FileSystem.documentDirectory + modelName;

        console.log("Copying to:", targetPath);
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
    await getLiteRTContext();
    const tInf = Date.now();

    let fullResponse = "";
    let firstToken = true;
    let tokenCount = 0;
    let tFirstToken = 0;

    return new Promise((resolve, reject) => {
        // Listen for tokens from Kotlin
        const subscription = LiteRTEventEmitter.addListener('onTokenGenerated', (event) => {
            if (event.token) {
                tokenCount++;
                if (firstToken) {
                    tFirstToken = Date.now();
                    const prefillTime = tFirstToken - tInf;
                    console.log(`\r\x1b[36m LOG  [LATENCY] Local LLM prefill (TTFT): ${prefillTime}ms\x1b[0m`);
                    firstToken = false;
                }
                fullResponse += event.token;
                onChunk(event.token);
            }

            if (event.done) {
                subscription.remove();
                const totalTime = Date.now() - tInf;
                const decodeTime = Date.now() - tFirstToken;
                const tps = decodeTime > 0 ? (tokenCount / (decodeTime / 1000)).toFixed(2) : 0;
                console.log(`\r\x1b[36m LOG  [LATENCY] Local LLM decode: ${decodeTime}ms for ${tokenCount} tokens (${tps} tokens/sec) | Total: ${totalTime}ms chars=${fullResponse.length}\x1b[0m`);

                const toolMatch = fullResponse.match(/\{[\s\S]*"name"\s*:\s*"get_(weather|current_location)"[\s\S]*\}/);
                if (toolMatch) {
                    console.log("Tool call detected in local inference!", toolMatch[0]);
                }

                resolve(fullResponse);
            }
        });

        // Trigger native generation
        LiteRTModule.generate(prompt)
            .catch((err: any) => {
                subscription.remove();
                console.error("Local inference error:", err);
                reject(err);
            });
    });
};
