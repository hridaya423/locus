#!/usr/bin/env Rscript
# ΔTE for one two-condition contrast from matched Ribo-seq and RNA-seq CDS counts: the deltaTE approach
# (Chothani et al. 2019, Curr Protoc Mol Biol 129:e108).
#
#   Rscript deltate_deseq2.R counts.tsv samples.tsv outdir reference target
#
# counts.tsv is gene x library (first column `gene`); samples.tsv has sample, pair, assay (ribo|rna) and condition.
# Three DESeq2 fits: ~ condition + assay + condition:assay on every library (the interaction term is ΔTE), ~ condition
# on the RNA-seq libraries alone (ΔRNA) and on the Ribo-seq libraries alone (ΔRibo). Each gene is then classed at
# padj < 0.05 with the same rule as riboseq.classify. Writes deltate_results.tsv, deltate_summary.json and
# deltate_scatter.png/.pdf (ΔRNA against ΔRibo, coloured by class).

suppressPackageStartupMessages({
  library(DESeq2)
  library(ggplot2)
  library(ggrepel)
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 5) stop("usage: deltate_deseq2.R counts.tsv samples.tsv outdir reference target")
counts <- as.matrix(read.delim(args[1], row.names = 1, check.names = FALSE))
samples <- read.delim(args[2], stringsAsFactors = FALSE, check.names = FALSE)
out <- args[3]
reference <- args[4]
target <- args[5]
dir.create(out, showWarnings = FALSE, recursive = TRUE)
storage.mode(counts) <- "integer"
samples <- samples[match(colnames(counts), samples$sample), ]
samples$condition <- factor(samples$condition, levels = c(reference, target))
samples$assay <- factor(samples$assay, levels = c("rna", "ribo"))
rownames(samples) <- samples$sample

# A gene is tested when it has at least 10 counts in as many libraries of each assay as the smaller condition holds.
smallest <- min(table(samples$condition[samples$assay == "ribo"]))
keep <- rowSums(counts[, samples$assay == "ribo", drop = FALSE] >= 10) >= smallest &
  rowSums(counts[, samples$assay == "rna", drop = FALSE] >= 10) >= smallest
tested <- counts[keep, , drop = FALSE]

fit <- function(m, meta, design, pick) {
  dds <- DESeqDataSetFromMatrix(m, meta, design)
  dds <- DESeq(dds, quiet = TRUE)
  name <- pick(resultsNames(dds))
  res <- results(dds, name = name, alpha = 0.05)
  list(name = name, log2fc = res$log2FoldChange, padj = res$padj, baseMean = res$baseMean)
}
te <- fit(tested, samples, ~ condition + assay + condition:assay, function(n) tail(grep("assayribo", n, value = TRUE), 1))
stopifnot(grepl(":|\\.", te$name))
rna <- fit(tested[, samples$assay == "rna", drop = FALSE], samples[samples$assay == "rna", ], ~condition, function(n) tail(n, 1))
ribo <- fit(tested[, samples$assay == "ribo", drop = FALSE], samples[samples$assay == "ribo", ], ~condition, function(n) tail(n, 1))

# The class rule, the same as riboseq.classify (run_* checks that the two agree gene by gene).
sig <- function(p) !is.na(p) & p < 0.05
classify <- function(padj_rna, lfc_rna, padj_ribo, lfc_ribo, padj_te, lfc_te) {
  s_te <- sig(padj_te); s_rna <- sig(padj_rna); s_ribo <- sig(padj_ribo)
  ifelse(s_te & !s_rna, "translationally regulated",
    ifelse(s_te & s_rna, ifelse((lfc_te > 0) != (lfc_rna > 0), "buffered", "intensified"),
      ifelse(s_rna & s_ribo, "transcriptional", "unchanged")))
}
table <- data.frame(
  gene = rownames(tested), base_mean = round(te$baseMean, 2),
  log2fc_rna = rna$log2fc, padj_rna = rna$padj, log2fc_ribo = ribo$log2fc, padj_ribo = ribo$padj, log2fc_te = te$log2fc, padj_te = te$padj,
  stringsAsFactors = FALSE
)
table$class <- classify(table$padj_rna, table$log2fc_rna, table$padj_ribo, table$log2fc_ribo, table$padj_te, table$log2fc_te)
table <- table[order(table$padj_te, -abs(table$log2fc_te)), ]
write.table(table, file.path(out, "deltate_results.tsv"), sep = "\t", quote = FALSE, row.names = FALSE)

CLASSES <- c("translationally regulated", "buffered", "transcriptional", "intensified", "unchanged")
counts_by_class <- setNames(as.list(sapply(CLASSES, function(k) sum(table$class == k))), CLASSES)
top <- head(table[table$class == "translationally regulated", ], 8)

# ---------------------------------------------------------------- figure
# ΔRNA (x) against ΔRibo (y); unchanged genes in grey underneath, the four classes on top in a colourblind-safe set
# (validated with the dataviz palette checker), the diagonal ΔRibo = ΔRNA dashed, legend with counts, top 8
# translationally regulated genes named. Same white-panel style as deseq2.R.
theme_locus <- function(base_size = 9) {
  theme_classic(base_size = base_size) +
    theme(
      axis.line = element_line(linewidth = 0.3, colour = "#52514e"), axis.ticks = element_line(linewidth = 0.3, colour = "#52514e"),
      axis.text = element_text(colour = "#52514e"), axis.title = element_text(colour = "#0b0b0b"),
      plot.title = element_text(size = base_size + 1, hjust = 0, colour = "#0b0b0b"), plot.title.position = "plot",
      plot.subtitle = element_text(size = base_size - 1, colour = "#52514e"),
      legend.title = element_blank(), legend.text = element_text(size = base_size - 1), legend.key.size = unit(8, "pt"),
      legend.background = element_blank(), legend.position = "inside",
      plot.margin = margin(6, 8, 4, 4), plot.background = element_rect(fill = "white", colour = NA)
    )
}
COLOURS <- c(`translationally regulated` = "#2a78d6", buffered = "#eb6834", transcriptional = "#2e9e6b", intensified = "#9b59c8", unchanged = "#c2c6ca")
shown <- table[!is.na(table$log2fc_rna) & !is.na(table$log2fc_ribo), ]
shown$class <- factor(shown$class, levels = CLASSES)
shown <- shown[order(shown$class != "unchanged"), ]  # grey first, so the classes draw on top
labels <- sapply(CLASSES, function(k) sprintf("%s (%s)", k, format(counts_by_class[[k]], big.mark = ",")))
lim <- max(abs(c(shown$log2fc_rna, shown$log2fc_ribo)), 1) * 1.05
scatter <- ggplot(shown, aes(log2fc_rna, log2fc_ribo)) +
  geom_abline(slope = 1, intercept = 0, linetype = "22", linewidth = 0.3, colour = "#52514e") +
  geom_hline(yintercept = 0, linewidth = 0.2, colour = "#c2c6ca") + geom_vline(xintercept = 0, linewidth = 0.2, colour = "#c2c6ca") +
  geom_point(aes(colour = class), size = 0.8, alpha = 0.85, stroke = 0) +
  geom_text_repel(data = top, aes(label = gene), size = 2.5, fontface = "italic", max.overlaps = 30, min.segment.length = 0.1,
                  segment.size = 0.25, segment.colour = "#52514e", seed = 1, box.padding = 0.3) +
  scale_colour_manual(values = COLOURS, labels = labels, breaks = CLASSES, drop = FALSE) +
  scale_x_continuous(limits = c(-lim, lim)) + scale_y_continuous(limits = c(-lim, lim)) + coord_equal() +
  guides(colour = guide_legend(override.aes = list(size = 2, alpha = 1))) +
  labs(x = sprintf("Δ RNA: log2 fold change of mRNA, %s vs %s", target, reference), y = "Δ Ribo: log2 fold change of ribosome footprints",
       title = sprintf("ΔTE classes at padj < 0.05, %s genes tested", format(nrow(table), big.mark = ","))) +
  theme_locus() + theme(legend.position.inside = c(0.02, 0.98), legend.justification = c(0, 1))
ggsave(file.path(out, "deltate_scatter.png"), scatter, width = 4.6, height = 4.4, dpi = 300, bg = "white")
ggsave(file.path(out, "deltate_scatter.pdf"), scatter, width = 4.6, height = 4.4, device = cairo_pdf, bg = "white")

write_json(list(
  genes = nrow(counts), genes_tested = nrow(table), genes_with_padj_te = sum(!is.na(table$padj_te)),
  classes = counts_by_class, te_up = sum(sig(table$padj_te) & table$log2fc_te > 0), te_down = sum(sig(table$padj_te) & table$log2fc_te < 0),
  top_translational = lapply(seq_len(nrow(top)), function(i) list(gene = top$gene[i], log2fc_te = round(top$log2fc_te[i], 3), padj_te = signif(top$padj_te[i], 3),
                                                                 log2fc_rna = round(top$log2fc_rna[i], 3), log2fc_ribo = round(top$log2fc_ribo[i], 3))),
  design = list(te = "~ condition + assay + condition:assay", rna = "~ condition (RNA-seq libraries)", ribo = "~ condition (Ribo-seq libraries)", te_coefficient = te$name,
                filter = sprintf(">= 10 counts in >= %d libraries of each assay", smallest)),
  versions = list(R = as.character(getRversion()), DESeq2 = as.character(packageVersion("DESeq2")), ggplot2 = as.character(packageVersion("ggplot2")))
), file.path(out, "deltate_summary.json"), auto_unbox = TRUE, digits = NA, pretty = TRUE)
