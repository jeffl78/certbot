""" This file contains parsing routines and object classes to help derive meaning from
raw lists of tokens from pyparsing. """

import abc
import logging
import six

from certbot import errors

logger = logging.getLogger(__name__)
COMMENT = " managed by Certbot"
COMMENT_BLOCK = ["#", COMMENT]

class WithLists(object):
    """ Abstract base class for "Parsable" objects whose underlying representation
    is a tree of lists.

    :param .ParseContext context: Contains contextual information that this object may need
        to perform parsing and dumping operations properly.
    """

    __metaclass__ = abc.ABCMeta

    def __init__(self, context):
        self._data = []
        self._tabs = None
        self.context = context

    @staticmethod
    @abc.abstractmethod
    def should_parse(lists):
        """ Returns whether the contests of `lists` can be parsed into this object.

        :returns: Whether `lists` can be parsed as this object.
        :rtype bool:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def parse(self, raw_list, add_spaces=False):
        """ Loads information into this object from underlying raw_list structure.
        Each Parsable object might make different assumptions about the structure of
        raw_list.

        :param list raw_list: A list or sublist of tokens from pyparsing, containing whitespace
            as separate tokens.
        :param bool add_spaces: If set, the method can and should manipulate and insert spacing
            between non-whitespace tokens and lists to delimit them.
        :raises .errors.MisconfigurationError: when the assumptions about the structure of
            raw_list are not met.
        """
        raise NotImplementedError()

    def child_context(self):
        """ Spans a child context (with this object as the parent). """
        if self.context is None:
            # This is really only for testing purposes. The context should otherwise never
            # be set to None.
            return ParseContext(self, None)
        return self.context.child(self)

    @abc.abstractmethod
    def iterate(self, expanded=False, match=None):
        """ Iterates across this object. If this object is a leaf object, only yields
        itself. If it contains references other parsing objects, and `expanded` is set,
        this function should first yield itself, then recursively iterate across all of them.
        :param bool expanded: Whether to recursively iterate on possible children.
        :param callable match: If provided, an object is only iterated if this callable
            returns True when called on that object.

        :returns: Iterator over desired objects.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_tabs(self):
        """ Guess at the tabbing style of this parsed object, based on whitespace.

        If this object is a leaf, it deducts the tabbing based on its own contents.
        Other objects may guess by calling `get_tabs` recursively on child objects.

        :returns: Guess at tabbing for this object. Should only return whitespace strings
            that does not contain newlines.
        :rtype str:
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def set_tabs(self, tabs="    "):
        """This tries to set and alter the tabbing of the current object to a desired
        whitespace string. Primarily meant for objects that were constructed, so they
        can conform to surrounding whitespace.

        :param str tabs: A whitespace string (not containing newlines).
        """
        raise NotImplementedError()

    def dump(self, include_spaces=False):
        """ Dumps back to pyparsing-like list tree. The opposite of `parse`.

        Note: if this object has not been modified, `dump` with `include_spaces=True`
        should always return the original input of `parse`.

        :param bool include_spaces: If set to False, magically hides whitespace tokens from
            dumped output.

        :returns: Pyparsing-like list tree.
        :rtype list:
        """
        return [elem.dump(include_spaces) for elem in self._data]

class Statements(WithLists):
    """ A group or list of "Statements". A Statement is either a Block or a Sentence.

    The underlying representation is simply a list of these Statement objects, with
    an extra `_trailing_whitespace` string to keep track of the whitespace that does not
    precede any more statements.
    """
    def __init__(self, context=None):
        super(Statements, self).__init__(context)
        self._trailing_whitespace = None

    # ======== Begin overridden functions

    @staticmethod
    def should_parse(lists):
        return isinstance(lists, list)

    def set_tabs(self, tabs="    "):
        """ Sets the tabbing for this set of statements. Does this by calling `set_tabs`
        on each of the child statements.

        Then, if a parent is present, sets trailing whitespace to parent tabbing. This
        is so that the trailing } of any Block that contains Statements lines up
        with parent tabbing.
        """
        for statement in self._data:
            statement.set_tabs(tabs)
        if self.context is not None and self.context.parent is not None:
            self._trailing_whitespace = "\n" + self.context.parent.get_tabs()

    def parse(self, parse_this, add_spaces=False):
        """ Parses a list of statements.
        Expects all elements in `parse_this` to be parseable by `context.parsing_hooks`,
        with an optional whitespace string at the last index of `parse_this`.
        """
        if not isinstance(parse_this, list):
            raise errors.MisconfigurationError("Statements parsing expects a list!")
        # If there's a trailing whitespace in the list of statements, keep track of it.
        if len(parse_this) > 0 and isinstance(parse_this[-1], six.string_types) \
                               and parse_this[-1].isspace():
            self._trailing_whitespace = parse_this[-1]
            parse_this = parse_this[:-1]
        self._data = [parse_raw(elem, self.child_context(), add_spaces) for elem in parse_this]

    def get_tabs(self):
        """ Takes a guess at the tabbing of all contained Statements by retrieving the
        tabbing of the first Statement."""
        if len(self._data) > 0:
            return self._data[0].get_tabs()
        return ""

    def dump(self, include_spaces=False):
        """ Dumps this object by first dumping each statement, then appending its
        trailing whitespace (if `include_spaces` is set) """
        data = super(Statements, self).dump(include_spaces)
        if include_spaces and self._trailing_whitespace is not None:
            return data + [self._trailing_whitespace]
        return data

    def iterate(self, expanded=False, match=None):
        """ Combines each statement's iterator.  """
        for elem in self._data:
            for sub_elem in elem.iterate(expanded, match):
                yield sub_elem

    # ======== End overridden functions

def _space_list(list_):
    """ Inserts whitespace between adjacent non-whitespace tokens. """
    spaced_statement = []
    for i in reversed(six.moves.xrange(len(list_))):
        spaced_statement.insert(0, list_[i])
        if i > 0 and not list_[i].isspace() and not list_[i-1].isspace():
            spaced_statement.insert(0, " ")
    return spaced_statement

class Sentence(WithLists):
    """ A list of words. Non-whitespace words are typically separated with whitespace tokens. """

    # ======== Begin overridden functions

    @staticmethod
    def should_parse(lists):
        """ Returns True if `lists` can be parseable as a `Sentence`-- that is,
        every element is a string type.

        :param list lists: The raw unparsed list to check.

        :returns: whether this lists is parseable by `Sentence`.
        """
        return isinstance(lists, list) and len(lists) > 0 and \
            all([isinstance(elem, six.string_types) for elem in lists])

    def parse(self, parse_this, add_spaces=False):
        """ Parses a list of string types into this object.
        If add_spaces is set, adds whitespace tokens between adjacent non-whitespace tokens."""
        if add_spaces:
            parse_this = _space_list(parse_this)
        if not isinstance(parse_this, list) or \
                any([not isinstance(elem, six.string_types) for elem in parse_this]):
            raise errors.MisconfigurationError("Sentence parsing expects a list of string types.")
        self._data = parse_this

    def iterate(self, expanded=False, match=None):
        """ Simply yields itself. """
        if match is None or match(self):
            yield self

    def set_tabs(self, tabs="    "):
        """ Sets the tabbing on this sentence. Inserts a newline and `tabs` at the
        beginning of `self._data`. """
        if self._data[0].isspace():
            return
        self._data.insert(0, "\n" + tabs)

    def dump(self, include_spaces=False):
        """ Dumps this sentence. If include_spaces is set, includes whitespace tokens."""
        if not include_spaces:
            return self.words
        return self._data

    def get_tabs(self):
        """ Guesses at the tabbing of this sentence. If the first element is whitespace,
        returns the whitespace after the rightmost newline in the string. """
        first = self._data[0]
        if not first.isspace():
            return ""
        rindex = first.rfind("\n")
        return first[rindex+1:]

    # ======== End overridden functions

    @property
    def words(self):
        """ Iterates over words, but without spaces. Like Unspaced List. """
        return [word.strip("\"\'") for word in self._data if not word.isspace()]

    def __getitem__(self, index):
        return self.words[index]

class Block(WithLists):
    """ Any sort of bloc, denoted by a block name and curly braces, like so:
    The parsed block:
        block name {
            content 1;
            content 2;
        }
    might be represented with the list [names, contents], where
        names = ["block", " ", "name", " "]
        contents = [["\n    ", "content", " ", "1"], ["\n    ", "content", " ", "2"], "\n"]
    """
    def __init__(self, context=None):
        super(Block, self).__init__(context)
        self.names = None
        self.contents = None

    @staticmethod
    def should_parse(lists):
        """ Returns True if `lists` can be parseable as a `Block`-- that is,
        it's got a length of 2, the first element is a `Sentence` and the second can be
        a `Statements`.

        :param list lists: The raw unparsed list to check.

        :returns: whether this lists is parseable by `Block`. """
        return isinstance(lists, list) and len(lists) == 2 and \
            Sentence.should_parse(lists[0]) and isinstance(lists[1], list)

    def set_tabs(self, tabs="    "):
        """ Sets tabs by setting equivalent tabbing on names, then adding tabbing
        to contents."""
        self.names.set_tabs(tabs)
        self.contents.set_tabs(tabs + "    ")

    def iterate(self, expanded=False, match=None):
        """ Iterator over self, and if expanded is set, over its contents. """
        if match is None or match(self):
            yield self
        if expanded:
            for elem in self.contents.iterate(expanded, match):
                yield elem

    def parse(self, parse_this, add_spaces=False):
        """ Parses a list that resembles a block.

        The assumptions that this routine makes are:
            1. the first element of `parse_this` is a valid Sentence.
            2. the second element of `parse_this` is a valid Statement.
        If add_spaces is set, we call it recursively on `names` and `contents`, and
        add an extra trailing space to `names` (to separate the block's opening bracket
        and the block name).
        """
        if not Block.should_parse(parse_this):
            raise errors.MisconfigurationError("Block parsing expects a list of length 2. "
                "First element should be a list of string types (the bloc names), "
                "and second should be another list of statements (the bloc content).")
        self.names = Sentence(self.child_context())
        if add_spaces:
            parse_this[0].append(" ")
        self.names.parse(parse_this[0], add_spaces)
        self.contents = Statements(self.child_context())
        self.contents.parse(parse_this[1], add_spaces)
        self._data = [self.names, self.contents]

    def get_tabs(self):
        """ Guesses tabbing by retrieving tabbing guess of self.names. """
        return self.names.get_tabs()

def _is_comment(parsed_obj):
    """ Checks whether parsed_obj is a comment.

    :param .WithLists parsed_obj:

    :returns: whether parsed_obj represents a comment sentence.
    :rtype bool:
    """
    if not isinstance(parsed_obj, Sentence):
        return False
    return parsed_obj.words[0] == "#"

def _is_certbot_comment(parsed_obj):
    """ Checks whether parsed_obj is a "managed by Certbot" comment.

    :param .WithLists parsed_obj:

    :returns: whether parsed_obj is a "managed by Certbot" comment.
    :rtype bool:
    """
    if not _is_comment(parsed_obj):
        return False
    if len(parsed_obj.words) != len(COMMENT_BLOCK):
        return False
    for i, word in enumerate(parsed_obj.words):
        if word != COMMENT_BLOCK[i]:
            return False
    return True

def _certbot_comment(context, preceding_spaces=4):
    """ A "Managed by Certbot" comment.
    :param int preceding_spaces: Number of spaces between the end of the previous
        statement and the comment.
    :returns: Sentence containing the comment.
    :rtype: .Sentence
    """
    result = Sentence(context)
    result.parse([" " * preceding_spaces] + COMMENT_BLOCK)
    return result

def _choose_parser(child_context, list_):
    """ Choose a parser from child_context, based on whichever hook returns True first. """
    for type_ in child_context.parsing_hooks:
        if type_.should_parse(list_):
            return type_(child_context)
    raise errors.MisconfigurationError(
        "None of the parsing hooks succeeded, so we don't know how to parse this set of lists.")

def parse_raw(lists_, context=None, add_spaces=False):
    """ Primary parsing factory function. Based on `context.parsing_hooks`, chooses
    WithLists objects with which it recursively parses `lists_`.

    :param list lists_: raw lists from pyparsing to parse.
    :param .ParseContext context: Context containing parsing hooks. If not set,
        uses default parsing hooks.
    :param bool add_spaces: Whether to pass add_spaces to the parser.

    :returns .WithLists: The parsed object.

    :raises errors.MisconfigurationError: If no parsing hook passes, and we can't
        determine which type to parse the raw lists into.
    """
    if context is None:
        context = ParseContext()
    if context.parsing_hooks is None:
        context.parsing_hooks = DEFAULT_PARSING_HOOKS
    parser = _choose_parser(context, lists_)
    parser.parse(lists_, add_spaces)
    return parser

# Default set of parsing hooks. By default, lists go to Statements.
DEFAULT_PARSING_HOOKS = (Block, Sentence, Statements)

class ParseContext(object):
    """ Context information held by parsed objects.

    :param .WithLists parent: The parent object containing the associated object.
    :param tuple parsing_hooks: Parsing order for `parse_raw` to use.
    """
    def __init__(self, parent=None, parsing_hooks=DEFAULT_PARSING_HOOKS):
        self.parsing_hooks = parsing_hooks
        self.parent = parent

    def child(self, parent):
        """ Spawn a child context.
        """
        return ParseContext(parent=parent, parsing_hooks=self.parsing_hooks)

