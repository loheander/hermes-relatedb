CREATE FULLTEXT INDEX `terms` FOR (n:`Chunk`|`Module`|`Doc`) ON EACH [n.`terms`] OPTIONS {indexConfig: {`fulltext.analyzer`: 'standard-no-stop-words',`fulltext.eventually_consistent`: false}};
