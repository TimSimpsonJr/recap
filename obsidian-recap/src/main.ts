import { Plugin } from "obsidian";

export default class RecapPlugin extends Plugin {
    async onload() {
        console.log("Recap plugin loaded");
    }

    onunload() {
        console.log("Recap plugin unloaded");
    }
}
