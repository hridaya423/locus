#!/usr/bin/env Rscript
# Pseudobulk differential expression per cluster: one DESeq2 fit (design ~ condition) on the summed raw counts of each
# cluster that has at least two samples per condition.
#
#   Rscript pseudobulk_deseq2.R pseudobulk_dir reference target outdir
#
# pseudobulk_dir holds cluster_<k>.counts.tsv (gene rows, one column per sample) and cells.tsv (cluster, sample,
# condition, cells, used). Writes pseudobulk_de.tsv (cluster, gene, baseMean, log2fc, lfcSE, pvalue, padj; apeglm-shrunk
# log2fc when apeglm converges, otherwise the plain estimate, as the `shrinkage` column says) and pseudobulk_summary.json.
# n is the number of samples per condition, never the number of cells: cells from one donor are not independent.

suppressPackageStartupMessages({
  library(DESeq2)
  library(apeglm)
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 4) stop("usage: pseudobulk_deseq2.R pseudobulk_dir reference target outdir")
pseudo <- args[1]
reference <- args[2]
target <- args[3]
out <- args[4]
dir.create(out, showWarnings = FALSE, recursive = TRUE)

cells <- read.delim(file.path(pseudo, "cells.tsv"), stringsAsFactors = FALSE, colClasses = c(cluster = "character", sample = "character"))
files <- list.files(pseudo, pattern = "^cluster_.*\\.counts\\.tsv$", full.names = TRUE)
results <- list()
summary <- list()

for (file in files) {
  cluster <- sub("^cluster_(.*)\\.counts\\.tsv$", "\\1", basename(file))
  counts <- read.delim(file, row.names = 1, check.names = FALSE)
  condition <- cells$condition[match(colnames(counts), cells$sample)]
  if (any(is.na(condition))) stop(sprintf("cluster %s: a sample column has no row in cells.tsv", cluster))
  per_condition <- table(factor(condition, levels = c(reference, target)))
  if (any(per_condition < 2)) {
    summary[[length(summary) + 1]] <- list(cluster = cluster, samples = as.list(per_condition), skipped = "fewer than 2 samples in a condition")
    next
  }
  coldata <- data.frame(condition = factor(condition, levels = c(reference, target)), row.names = colnames(counts))
  dds <- DESeqDataSetFromMatrix(as.matrix(counts), coldata, ~condition)
  dds <- dds[rowSums(counts(dds)) >= 10, ]
  dds <- DESeq(dds, quiet = TRUE)
  unshrunk <- results(dds, alpha = 0.05)
  shrunk <- tryCatch(lfcShrink(dds, coef = 2, res = unshrunk, type = "apeglm", quiet = TRUE), error = function(e) NULL)
  res <- if (is.null(shrunk)) unshrunk else shrunk
  table <- data.frame(
    cluster = cluster, gene = rownames(res), baseMean = res$baseMean, log2fc = res$log2FoldChange, lfcSE = res$lfcSE,
    pvalue = res$pvalue, padj = res$padj, shrinkage = if (is.null(shrunk)) "none" else "apeglm", stringsAsFactors = FALSE
  )
  table <- table[order(table$padj, table$pvalue), ]
  results[[length(results) + 1]] <- table
  tested <- table[!is.na(table$padj), ]
  summary[[length(summary) + 1]] <- list(
    cluster = cluster, samples = as.list(per_condition), genes = nrow(dds), genes_tested = nrow(tested),
    significant = sum(tested$padj < 0.05), up = sum(tested$padj < 0.05 & tested$log2fc > 0), down = sum(tested$padj < 0.05 & tested$log2fc < 0),
    shrinkage = if (is.null(shrunk)) "none" else "apeglm"
  )
  message(sprintf("  cluster %s: %d genes tested, %d at padj < 0.05", cluster, nrow(tested), sum(tested$padj < 0.05)))
}

all <- if (length(results)) do.call(rbind, results) else data.frame(cluster = character(), gene = character(), baseMean = numeric(), log2fc = numeric(),
                                                                     lfcSE = numeric(), pvalue = numeric(), padj = numeric(), shrinkage = character())
all$baseMean <- signif(all$baseMean, 5)
all$log2fc <- signif(all$log2fc, 5)
all$lfcSE <- signif(all$lfcSE, 4)
all$pvalue <- signif(all$pvalue, 4)
all$padj <- signif(all$padj, 4)
write.table(all, file.path(out, "pseudobulk_de.tsv"), sep = "\t", quote = FALSE, row.names = FALSE)
write_json(list(
  clusters = summary,
  versions = list(R = as.character(getRversion()), DESeq2 = as.character(packageVersion("DESeq2")), apeglm = as.character(packageVersion("apeglm")))
), file.path(out, "pseudobulk_summary.json"), auto_unbox = TRUE, digits = NA, pretty = TRUE)
