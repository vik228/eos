return {
  {
    "LazyVim/LazyVim",
    init = function()
      require("config.options")
      require("config.autocmds")
      require("config.eos_keymaps").setup()
    end,
  },
  { "stevearc/oil.nvim", opts = {} },
  { "ThePrimeagen/harpoon", branch = "harpoon2", opts = {} },
  { "mfussenegger/nvim-dap" },
  { "folke/trouble.nvim", opts = {} },
  { "folke/flash.nvim", opts = {} },
  { "lewis6991/gitsigns.nvim", opts = {} },
  { "sindrets/diffview.nvim" },
}
