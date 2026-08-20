#!/usr/bin/env python3
"""
Tests for TWiki → GFM Converter
================================
Run with: pytest test_converter.py -v
"""

import pytest
from twiki2gfm import TWikiConverter


@pytest.fixture
def conv():
    """Fresh converter instance for each test."""
    return TWikiConverter()


# ═══════════════════════════════════════════════════════════════════
#  Section 1: META lines
# ═══════════════════════════════════════════════════════════════════

class TestMeta:
    def test_topicinfo(self, conv):
        inp = '%META:TOPICINFO{author="user" date="123" format="1.1"}%\nHello'
        assert conv.convert(inp).strip() == 'Hello'

    def test_topicparent(self, conv):
        inp = '%META:TOPICPARENT{name="WebHome"}%\nContent'
        assert conv.convert(inp).strip() == 'Content'

    def test_fileattachment(self, conv):
        inp = '%META:FILEATTACHMENT{name="file.pdf" size="1234"}%\nText'
        assert conv.convert(inp).strip() == 'Text'

    def test_multiple_meta(self, conv):
        inp = (
            '%META:TOPICINFO{author="x"}%\n'
            '%META:TOPICPARENT{name="Y"}%\n'
            'Real content here'
        )
        assert conv.convert(inp).strip() == 'Real content here'


# ═══════════════════════════════════════════════════════════════════
#  Section 2: Headings
# ═══════════════════════════════════════════════════════════════════

class TestHeadings:
    def test_h1(self, conv):
        assert '# Title' in conv.convert('---+ Title')

    def test_h2(self, conv):
        assert '## Title' in conv.convert('---++ Title')

    def test_h3(self, conv):
        assert '### Title' in conv.convert('---+++ Title')

    def test_h4(self, conv):
        assert '#### Title' in conv.convert('---++++ Title')

    def test_h5(self, conv):
        assert '##### Title' in conv.convert('---+++++ Title')

    def test_h6(self, conv):
        assert '###### Title' in conv.convert('---++++++ Title')

    def test_extra_dashes(self, conv):
        """----++ should still be h2 (extra dashes are OK)."""
        assert '## CADI' in conv.convert('----++ CADI')

    def test_toc_exclusion(self, conv):
        """---++!! strips !! and converts normally."""
        assert '## Hidden' in conv.convert('---++!! Hidden')

    def test_auto_numbered(self, conv):
        """---## auto-numbered heading → ##"""
        assert '## Auto' in conv.convert('---## Auto')


# ═══════════════════════════════════════════════════════════════════
#  Section 3: Inline formatting
# ═══════════════════════════════════════════════════════════════════

class TestInlineFormatting:
    def test_bold(self, conv):
        """TWiki *bold* → GFM **bold** (NOT italic!)"""
        result = conv.convert('This is *bold* text')
        assert '**bold**' in result
        assert '*bold*' not in result.replace('**bold**', '')

    def test_italic(self, conv):
        """TWiki _italic_ → GFM *italic*"""
        result = conv.convert('This is _italic_ text')
        assert '*italic*' in result

    def test_bold_italic(self, conv):
        """TWiki __bolditalic__ → GFM ***bolditalic***"""
        result = conv.convert('This is __bolditalic__ text')
        assert '***bolditalic***' in result

    def test_fixed(self, conv):
        """TWiki =code= → GFM `code`"""
        result = conv.convert('Use =command= here')
        assert '`command`' in result

    def test_bold_fixed(self, conv):
        """TWiki ==bold code== → GFM **`bold code`**"""
        result = conv.convert('Use ==bold code== here')
        assert '**`bold code`**' in result

    def test_no_match_with_spaces(self, conv):
        """* not bold * should NOT be converted."""
        result = conv.convert('This is * not bold * text')
        assert '**' not in result

    def test_bold_at_line_start(self, conv):
        result = conv.convert('*bold* at start')
        assert '**bold**' in result

    def test_bold_before_punctuation(self, conv):
        result = conv.convert('word *bold*.')
        assert '**bold**.' in result


# ═══════════════════════════════════════════════════════════════════
#  Section 4: Horizontal rules
# ═══════════════════════════════════════════════════════════════════

class TestHorizontalRules:
    def test_three_dashes(self, conv):
        result = conv.convert('above\n---\nbelow')
        assert '---' in result

    def test_many_dashes(self, conv):
        result = conv.convert('above\n------\nbelow')
        assert '---' in result

    def test_not_confused_with_heading(self, conv):
        """---++ should be heading, not hr."""
        result = conv.convert('---++ Title')
        assert '## Title' in result


# ═══════════════════════════════════════════════════════════════════
#  Section 5: Lists
# ═══════════════════════════════════════════════════════════════════

class TestLists:
    def test_bullet_level1(self, conv):
        result = conv.convert('   * Item one')
        assert '- Item one' in result

    def test_bullet_level2(self, conv):
        result = conv.convert('      * Nested')
        assert '  - Nested' in result

    def test_bullet_level3(self, conv):
        result = conv.convert('         * Deep')
        assert '    - Deep' in result

    def test_numbered_arabic(self, conv):
        result = conv.convert('   1. First')
        assert '1. First' in result

    def test_numbered_alpha(self, conv):
        """A. → 1. (GFM only supports arabic)"""
        result = conv.convert('   A. Alpha')
        assert '1. Alpha' in result

    def test_numbered_roman(self, conv):
        """I. → 1."""
        result = conv.convert('   I. Roman')
        assert '1. Roman' in result

    def test_definition_list(self, conv):
        result = conv.convert('   $ Term: This is the definition')
        assert '**Term:** This is the definition' in result

    def test_multiple_bullets(self, conv):
        inp = '   * One\n   * Two\n   * Three'
        result = conv.convert(inp)
        assert '- One' in result
        assert '- Two' in result
        assert '- Three' in result


# ═══════════════════════════════════════════════════════════════════
#  Section 6: Tables
# ═══════════════════════════════════════════════════════════════════

class TestTables:
    def test_simple_table_with_header(self, conv):
        inp = '| *Name* | *Age* |\n| Alice | 30 |\n| Bob | 25 |'
        result = conv.convert(inp)
        assert '| Name | Age |' in result
        assert '| --- | --- |' in result
        assert '| Alice | 30 |' in result

    def test_table_without_header(self, conv):
        """Tables without bold first row still get a separator."""
        inp = '| cell1 | cell2 |\n| cell3 | cell4 |'
        result = conv.convert(inp)
        assert '---' in result  # separator added

    def test_rowspan_marker(self, conv):
        """^ cells should become empty."""
        inp = '| *H1* | *H2* |\n| data | data2 |\n| ^ | data3 |'
        result = conv.convert(inp)
        assert '|  |' in result or '| |' in result


# ═══════════════════════════════════════════════════════════════════
#  Section 7: Links
# ═══════════════════════════════════════════════════════════════════

class TestLinks:
    def test_external_with_label(self, conv):
        result = conv.convert('[[http://example.com][Click here]]')
        assert '[Click here](http://example.com)' in result

    def test_external_without_label(self, conv):
        result = conv.convert('[[http://example.com]]')
        assert '[http://example.com](http://example.com)' in result

    def test_internal_with_label(self, conv):
        result = conv.convert('[[TopicName][Read more]]')
        assert '[Read more](TopicName)' in result

    def test_internal_simple(self, conv):
        """[[TopicName]] → plain text (won't resolve as link)."""
        result = conv.convert('See [[TopicName]]')
        assert 'TopicName' in result

    def test_escaped_link(self, conv):
        """![[Topic]] → literal text with escaped brackets"""
        result = conv.convert('![[Topic]]')
        assert '\\[\\[Topic\\]\\]' in result

    def test_anchor_link(self, conv):
        result = conv.convert('[[#MyAnchor][Jump]]')
        assert '[Jump](#myanchor)' in result

    def test_bare_url_passthrough(self, conv):
        url = 'http://cms.cern.ch/iCMS/page'
        result = conv.convert(url)
        assert url in result


# ═══════════════════════════════════════════════════════════════════
#  Section 8: TWiki Variables
# ═══════════════════════════════════════════════════════════════════

class TestVariables:
    def test_br(self, conv):
        result = conv.convert('line1 %BR% line2')
        assert '<br>' in result
        assert '%BR%' not in result

    def test_toc_removed(self, conv):
        result = conv.convert('%TOC%\n\nContent')
        assert '%TOC%' not in result
        assert 'Content' in result

    def test_icon_to_emoji(self, conv):
        result = conv.convert('%ICON{"tip"}% Hint')
        assert '💡' in result
        assert '%ICON' not in result

    def test_attachurl(self, conv):
        result = conv.convert('%ATTACHURL%/diagram.png')
        assert 'diagram.png' in result
        assert '%ATTACHURL%' not in result

    def test_vbar(self, conv):
        result = conv.convert('%VBAR%')
        assert '\\|' in result

    def test_generic_variable_stripped(self, conv):
        result = conv.convert('%SOMEVARIABLE% text')
        assert '%SOMEVARIABLE%' not in result
        assert 'text' in result

    def test_table_directive_removed(self, conv):
        result = conv.convert('%TABLE{sort="on"}%\n| a | b |')
        assert '%TABLE' not in result


# ═══════════════════════════════════════════════════════════════════
#  Section 9: Color blocks
# ═══════════════════════════════════════════════════════════════════

class TestColorBlocks:
    def test_red_block(self, conv):
        inp = '%ICON{led-red}% %RED%\nQuestion text\n%ENDCOLOR%'
        result = conv.convert(inp)
        assert '> 🔴 Question text' in result
        assert '%RED%' not in result
        assert '%ENDCOLOR%' not in result

    def test_green_block(self, conv):
        inp = '%ICON{led-green}% %GREEN%\nAnswer text\n%ENDCOLOR%'
        result = conv.convert(inp)
        assert '> 🟢 Answer text' in result

    def test_multiline_color_block(self, conv):
        inp = '%ICON{led-green}% %GREEN%\nLine 1\nLine 2\n%ENDCOLOR%'
        result = conv.convert(inp)
        assert '> 🟢 Line 1' in result
        assert '> Line 2' in result

    def test_br_inside_color_block(self, conv):
        inp = '%RED%\ntext %BR% more\n%ENDCOLOR%'
        result = conv.convert(inp)
        assert '<br>' in result
        assert '%BR%' not in result

    def test_color_without_icon(self, conv):
        """Color block without preceding ICON should still work."""
        inp = '%RED%\nRed text\n%ENDCOLOR%'
        result = conv.convert(inp)
        assert '> 🔴 Red text' in result


# ═══════════════════════════════════════════════════════════════════
#  Section 10: Verbatim blocks
# ═══════════════════════════════════════════════════════════════════

class TestVerbatim:
    def test_basic_verbatim(self, conv):
        inp = 'Before\n<verbatim>\ncode here\n</verbatim>\nAfter'
        result = conv.convert(inp)
        assert '```' in result
        assert 'code here' in result
        assert '<verbatim>' not in result

    def test_verbatim_with_language(self, conv):
        inp = '<verbatim class="python">\nprint("hi")\n</verbatim>'
        result = conv.convert(inp)
        assert '```python' in result

    def test_verbatim_content_not_processed(self, conv):
        """Content inside verbatim must NOT be converted."""
        inp = '<verbatim>\n*not bold* ---++ not heading\n</verbatim>'
        result = conv.convert(inp)
        assert '*not bold*' in result  # should NOT become **not bold**
        assert '---++' in result       # should NOT become ##

    def test_pre_block(self, conv):
        inp = '<pre>\npreformatted\n</pre>'
        result = conv.convert(inp)
        assert '```' in result
        assert 'preformatted' in result


# ═══════════════════════════════════════════════════════════════════
#  Section 11: HTML tags
# ═══════════════════════════════════════════════════════════════════

class TestHtmlTags:
    def test_br_normalization(self, conv):
        result = conv.convert('text<br />more')
        assert 'text<br>more' in result

    def test_br_self_closing(self, conv):
        result = conv.convert('text<br/>more')
        assert 'text<br>more' in result

    def test_bold_html(self, conv):
        result = conv.convert('<b>bold</b>')
        assert '**bold**' in result

    def test_italic_html(self, conv):
        result = conv.convert('<i>italic</i>')
        assert '*italic*' in result

    def test_em_html(self, conv):
        result = conv.convert('<em>emphasis</em>')
        assert '*emphasis*' in result

    def test_strike_html(self, conv):
        result = conv.convert('<strike>old</strike>')
        assert '~~old~~' in result

    def test_del_html(self, conv):
        result = conv.convert('<del>deleted</del>')
        assert '~~deleted~~' in result

    def test_nop_removed(self, conv):
        result = conv.convert('A<nop>B')
        assert 'AB' in result
        assert '<nop>' not in result

    def test_noautolink_stripped(self, conv):
        result = conv.convert('<noautolink>Text</noautolink>')
        assert 'Text' in result
        assert '<noautolink>' not in result


# ═══════════════════════════════════════════════════════════════════
#  Section 12: Signatures
# ═══════════════════════════════════════════════════════════════════

class TestSignatures:
    def test_signature_with_main(self, conv):
        result = conv.convert('-- Main.JohnDoe - 2012-07-11')
        assert '— JohnDoe, 2012-07-11' in result

    def test_signature_date_format2(self, conv):
        result = conv.convert('-- Main.GianPieroDiGiovanni - 11-Jul-2012')
        assert '— GianPieroDiGiovanni, 11-Jul-2012' in result

    def test_signature_without_web(self, conv):
        result = conv.convert('-- JaneDoe - 2023-01-15')
        assert '— JaneDoe, 2023-01-15' in result


# ═══════════════════════════════════════════════════════════════════
#  Section 13: WikiWord escapes
# ═══════════════════════════════════════════════════════════════════

class TestWikiWordEscapes:
    def test_escaped_wikiword(self, conv):
        result = conv.convert('Use !WikiWord here')
        assert 'WikiWord' in result
        assert '!WikiWord' not in result

    def test_escaped_tev(self, conv):
        """!TeV → TeV (from real CMS files)."""
        result = conv.convert('8 !TeV')
        assert '8 TeV' in result
        assert '!TeV' not in result

    def test_main_prefix(self, conv):
        result = conv.convert('by Main.UserName')
        assert 'UserName' in result
        assert 'Main.' not in result


# ═══════════════════════════════════════════════════════════════════
#  Section 14: Special characters
# ═══════════════════════════════════════════════════════════════════

class TestSpecialChars:
    def test_html_entities(self, conv):
        result = conv.convert('A &amp; B &lt; C &gt; D')
        assert 'A & B < C > D' in result

    def test_nbsp(self, conv):
        result = conv.convert('word&nbsp;word')
        assert 'word word' in result


# ═══════════════════════════════════════════════════════════════════
#  Section 15: Validation
# ═══════════════════════════════════════════════════════════════════

class TestValidation:
    def test_clean_output_passes(self, conv):
        result = conv.convert('# Hello\n\nSome text')
        checks = conv.validate(result)
        assert any('✅' in c for c in checks)

    def test_leftover_meta_fails(self, conv):
        checks = conv.validate('%META:TOPICINFO{bad}%\ntext')
        assert any('❌' in c for c in checks)

    def test_leftover_nop_fails(self, conv):
        checks = conv.validate('text <nop> more')
        assert any('❌' in c for c in checks)


# ═══════════════════════════════════════════════════════════════════
#  Real-world test: the actual CMS file
# ═══════════════════════════════════════════════════════════════════

class TestRealFile:
    """Tests based on the actual ZZ4lXSecAt8TeVHPAforICHEP.txt file."""

    SAMPLE = (
        '%META:TOPICINFO{author="digiovan" date="1342032084" format="1.1" version="1.2"}%\n'
        '%META:TOPICPARENT{name="TWikiSMP-MUO"}%\n'
        '---+ Measurement of ZZ Cross Section at 8 !TeV\n'
        '\n'
        '---++ Contact People\n'
        '\n'
        '   * Cristina Botta\n'
        '   * Giovanni Petrucciani\n'
        '   * Mario Pellicciotti\n'
        '\n'
        '----++ CADI\n'
        '\n'
        '   * http://cms.cern.ch/iCMS/jsp/analysis/admin/analysismanagement.jsp?ancode=SMP-12-013\n'
        '\n'
        '----++ Questions/Answers\n'
        '\n'
        '%ICON{led-red}% %RED%  \n'
        'Are the efficiencies taken from central numbers or recomputed individually for the analysis?\n'
        '%ENDCOLOR%\n'
        '\n'
        '%ICON{led-green}% %GREEN%  \n'
        'They are recomputed\n'
        '%ENDCOLOR%\n'
        '\n'
        '-- Main.GianPieroDiGiovanni - 11-Jul-2012\n'
    )

    def test_meta_stripped(self, conv):
        result = conv.convert(self.SAMPLE)
        assert '%META:' not in result

    def test_h1_correct(self, conv):
        result = conv.convert(self.SAMPLE)
        assert '# Measurement of ZZ Cross Section at 8 TeV' in result

    def test_h2_correct(self, conv):
        result = conv.convert(self.SAMPLE)
        assert '## Contact People' in result

    def test_h2_extra_dashes(self, conv):
        result = conv.convert(self.SAMPLE)
        assert '## CADI' in result
        assert '## Questions/Answers' in result

    def test_bullet_list(self, conv):
        result = conv.convert(self.SAMPLE)
        assert '- Cristina Botta' in result
        assert '- Giovanni Petrucciani' in result
        assert '- Mario Pellicciotti' in result

    def test_tev_escape(self, conv):
        result = conv.convert(self.SAMPLE)
        assert '!TeV' not in result
        assert 'TeV' in result

    def test_red_blockquote(self, conv):
        result = conv.convert(self.SAMPLE)
        assert '> 🔴' in result

    def test_green_blockquote(self, conv):
        result = conv.convert(self.SAMPLE)
        assert '> 🟢' in result

    def test_no_endcolor(self, conv):
        result = conv.convert(self.SAMPLE)
        assert '%ENDCOLOR%' not in result

    def test_no_icon_raw(self, conv):
        result = conv.convert(self.SAMPLE)
        assert '%ICON{' not in result

    def test_signature_clean(self, conv):
        result = conv.convert(self.SAMPLE)
        assert '— GianPieroDiGiovanni, 11-Jul-2012' in result
        assert '-- Main.' not in result

    def test_url_preserved(self, conv):
        result = conv.convert(self.SAMPLE)
        assert 'http://cms.cern.ch/iCMS/jsp/analysis/admin/analysismanagement.jsp' in result

    def test_validation_passes(self, conv):
        result = conv.convert(self.SAMPLE)
        checks = conv.validate(result)
        assert any('✅' in c for c in checks)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
